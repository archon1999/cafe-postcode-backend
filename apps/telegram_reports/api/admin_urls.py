from django.urls import path

from apps.telegram_reports.api.admin_views import (
    TelegramBranchSubscriptionListView,
    TelegramBranchSubscriptionRevokeView,
    TelegramLinkTokenIssueView,
)


urlpatterns = [
    path("link-token/", TelegramLinkTokenIssueView.as_view(), name="telegram-link-token-issue"),
    path("subscriptions/", TelegramBranchSubscriptionListView.as_view(), name="telegram-subscription-list"),
    path(
        "subscriptions/<uuid:pk>/",
        TelegramBranchSubscriptionRevokeView.as_view(),
        name="telegram-subscription-revoke",
    ),
]
