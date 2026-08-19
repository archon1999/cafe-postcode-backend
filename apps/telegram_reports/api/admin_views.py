import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.telegram_reports.models import TelegramBranchSubscription, TelegramLinkToken
from apps.devices.models import SecurityEvent
from apps.devices.security import record_security_event
from common.api.admin_permissions import AdminPermissionRequiredMixin, AdminRecentMFARequiredMixin
from common.api.scopes import get_request_restaurant


logger = logging.getLogger(__name__)


def _require_superuser(request):
    if not request.user.is_superuser:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Only platform superusers can manage Telegram report links.")


class TelegramLinkTokenIssueView(AdminRecentMFARequiredMixin, APIView):
    def post(self, request):
        _require_superuser(request)
        restaurant = get_request_restaurant(request)
        if not restaurant.is_active:
            return Response(
                {"detail": "Telegram cannot be linked to an inactive restaurant."},
                status=status.HTTP_409_CONFLICT,
            )

        bot_username = settings.TELEGRAM_REPORTS_BOT_USERNAME.lstrip("@").strip()
        if not bot_username:
            return Response(
                {"detail": "Telegram reports bot username is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        token, raw_token = TelegramLinkToken.issue(
            restaurant=restaurant,
            issued_by=request.user,
            ttl_minutes=5,
        )
        logger.info(
            "Telegram link token issued",
            extra={
                "user_id": str(request.user.pk),
                "restaurant_id": str(restaurant.pk),
                "telegram_link_token_id": str(token.pk),
            },
        )
        record_security_event(
            event_type='TELEGRAM_LINK_TOKEN_ISSUED',
            severity=SecurityEvent.Severity.INFO,
            request=request,
            restaurant=restaurant,
            actor=request.user,
            result='SUCCESS',
            metadata={'linkArtifactId': str(token.pk)},
        )
        return Response(
            {
                "id": str(token.pk),
                "restaurantId": str(restaurant.pk),
                "restaurantName": restaurant.name,
                "startUrl": f"https://t.me/{bot_username}?start={raw_token}",
                "expiresAt": token.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class TelegramBranchSubscriptionListView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        _require_superuser(request)
        restaurant = get_request_restaurant(request)
        subscriptions = (
            TelegramBranchSubscription.objects.filter(restaurant=restaurant)
            .select_related("account")
            .order_by("account__username", "account__telegram_user_id")
        )
        return Response(
            {
                "data": [
                    {
                        "id": str(subscription.pk),
                        "telegramUserId": str(subscription.account.telegram_user_id),
                        "username": subscription.account.username,
                        "firstName": subscription.account.first_name,
                        "notificationsEnabled": subscription.account.notifications_enabled,
                        "linkedAt": subscription.created_at,
                    }
                    for subscription in subscriptions
                ]
            }
        )


class TelegramBranchSubscriptionRevokeView(AdminRecentMFARequiredMixin, APIView):
    def delete(self, request, pk):
        _require_superuser(request)
        restaurant = get_request_restaurant(request)
        subscription = get_object_or_404(
            TelegramBranchSubscription.objects.select_related("account"),
            pk=pk,
            restaurant=restaurant,
        )
        account_id = subscription.account.telegram_user_id
        subscription.delete()
        logger.warning(
            "Telegram branch subscription revoked",
            extra={
                "user_id": str(request.user.pk),
                "restaurant_id": str(restaurant.pk),
                "telegram_user_id": str(account_id),
            },
        )
        record_security_event(
            event_type='TELEGRAM_SUBSCRIPTION_REVOKED',
            severity=SecurityEvent.Severity.MEDIUM,
            request=request,
            restaurant=restaurant,
            actor=request.user,
            result='SUCCESS',
            metadata={'subscriptionId': str(pk)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
