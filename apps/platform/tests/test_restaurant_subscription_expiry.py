from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule

from apps.platform.models import BusinessPartner, RestaurantEntitlement
from apps.platform.services import EXPIRY_SCHEDULE_FUNC, EXPIRY_SCHEDULE_NAME, ensure_expiry_schedule, expire_restaurant_entitlements
from apps.restaurants.models import Restaurant


class RestaurantSubscriptionExpiryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        partner = BusinessPartner.objects.create(
            inn='987654321',
            company_name='Expiry Partner',
            legal_name='Expiry Partner LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.expired_restaurant = Restaurant.objects.create(
            business_partner=partner,
            name='Expired Restaurant',
            legal_name='Expired Restaurant LLC',
            is_active=True,
            activated_at=timezone.now(),
        )
        cls.active_restaurant = Restaurant.objects.create(
            business_partner=partner,
            name='Active Restaurant',
            legal_name='Active Restaurant LLC',
            is_active=True,
            activated_at=timezone.now(),
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.expired_restaurant,
            is_active=True,
            starts_on=date(2026, 3, 1),
            expires_on=date(2026, 4, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.active_restaurant,
            is_active=True,
            starts_on=date(2026, 4, 1),
            expires_on=date(2026, 5, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
        )

    def test_expire_restaurant_entitlements_deactivates_only_expired_rows(self):
        with patch('apps.platform.services.restaurant_subscriptions.timezone.localdate', return_value=date(2026, 4, 7)):
            expired_count = expire_restaurant_entitlements()

        self.assertEqual(expired_count, 1)
        self.expired_restaurant.refresh_from_db()
        self.active_restaurant.refresh_from_db()

        self.assertFalse(self.expired_restaurant.is_active)
        self.assertFalse(self.expired_restaurant.entitlement.is_active)
        self.assertIsNotNone(self.expired_restaurant.deactivated_at)
        self.assertTrue(self.active_restaurant.is_active)
        self.assertTrue(self.active_restaurant.entitlement.is_active)

    def test_ensure_expiry_schedule_is_idempotent(self):
        ensure_expiry_schedule()
        ensure_expiry_schedule()

        schedules = Schedule.objects.filter(name=EXPIRY_SCHEDULE_NAME, func=EXPIRY_SCHEDULE_FUNC)

        self.assertEqual(schedules.count(), 1)
        self.assertEqual(schedules.first().schedule_type, Schedule.HOURLY)
