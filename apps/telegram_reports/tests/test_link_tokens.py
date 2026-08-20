from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIRequestFactory, APITestCase

from apps.restaurants.models import Restaurant
from apps.telegram_reports.models import (
    TelegramAccount,
    TelegramBranchSubscription,
    TelegramLinkToken,
)
from apps.users.services import AuthSessionService


User = get_user_model()


@override_settings(TELEGRAM_REPORTS_BOT_USERNAME="postcode_reports_bot")
class TelegramLinkTokenAdminApiTests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="platform-owner", password="Strong-pass-123")
        self.restaurant = Restaurant.objects.create(name="Qamish")
        self.second_restaurant = Restaurant.objects.create(name="Chilonzor")
        _, session = AuthSessionService().issue(
            user=self.superuser,
            request=APIRequestFactory().post('/'),
            surface='admin',
            mfa_verified_at=timezone.now(),
        )
        self.client.force_authenticate(self.superuser, session)

    def headers(self, restaurant=None):
        return {"HTTP_X_ADMIN_RESTAURANT_ID": str((restaurant or self.restaurant).pk)}

    def test_issue_returns_five_minute_single_use_deep_link_and_hashes_secret(self):
        before = timezone.now()

        response = self.client.post(
            "/api/v1/admin/telegram-reports/link-token/",
            {},
            format="json",
            **self.headers(),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["startUrl"].startswith("https://t.me/postcode_reports_bot?start=tgr_"))
        raw_token = response.data["startUrl"].partition("?start=")[2]
        link_token = TelegramLinkToken.objects.get(pk=response.data["id"])
        self.assertNotEqual(link_token.token_hash, raw_token)
        self.assertEqual(link_token.token_hash, TelegramLinkToken.hash_token(raw_token))
        self.assertGreater(link_token.expires_at, before)
        self.assertLessEqual(link_token.expires_at, before + timedelta(minutes=5, seconds=2))

    def test_issuing_new_link_revokes_previous_unconsumed_link(self):
        first = self.client.post(
            "/api/v1/admin/telegram-reports/link-token/",
            {},
            format="json",
            **self.headers(),
        )
        second = self.client.post(
            "/api/v1/admin/telegram-reports/link-token/",
            {},
            format="json",
            **self.headers(),
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        first_token = TelegramLinkToken.objects.get(pk=first.data["id"])
        self.assertIsNotNone(first_token.revoked_at)
        self.assertIsNone(TelegramLinkToken.objects.get(pk=second.data["id"]).revoked_at)

    def test_non_superuser_cannot_issue_link(self):
        user = User.objects.create_user(username="restaurant-admin", password="Strong-pass-123")
        self.client.force_authenticate(user)

        response = self.client.post(
            "/api/v1/admin/telegram-reports/link-token/",
            {},
            format="json",
            **self.headers(),
        )

        self.assertEqual(response.status_code, 403)

    def test_subscription_list_and_revoke_are_restaurant_scoped(self):
        account = TelegramAccount.objects.create(telegram_user_id=101, chat_id=101, username="owner")
        own_subscription = TelegramBranchSubscription.objects.create(account=account, restaurant=self.restaurant)
        foreign_subscription = TelegramBranchSubscription.objects.create(
            account=account,
            restaurant=self.second_restaurant,
        )

        listed = self.client.get(
            "/api/v1/admin/telegram-reports/subscriptions/",
            **self.headers(),
        )
        listed_all = self.client.get("/api/v1/admin/telegram-reports/subscriptions/")
        foreign_revoke = self.client.delete(
            f"/api/v1/admin/telegram-reports/subscriptions/{foreign_subscription.pk}/",
            **self.headers(),
        )
        all_scope_foreign_revoke = self.client.delete(
            f"/api/v1/admin/telegram-reports/subscriptions/{foreign_subscription.pk}/"
        )
        own_revoke = self.client.delete(
            f"/api/v1/admin/telegram-reports/subscriptions/{own_subscription.pk}/",
            **self.headers(),
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.data["data"]], [str(own_subscription.pk)])
        self.assertEqual(listed_all.status_code, 200)
        self.assertEqual(
            {item["id"] for item in listed_all.data["data"]},
            {str(own_subscription.pk), str(foreign_subscription.pk)},
        )
        self.assertEqual(
            {item["restaurantName"] for item in listed_all.data["data"]},
            {self.restaurant.name, self.second_restaurant.name},
        )
        self.assertEqual(foreign_revoke.status_code, 404)
        self.assertEqual(all_scope_foreign_revoke.status_code, 204)
        self.assertEqual(own_revoke.status_code, 204)
        self.assertFalse(TelegramBranchSubscription.objects.filter(pk=foreign_subscription.pk).exists())
