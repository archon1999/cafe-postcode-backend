from django.urls import path

from apps.telegram_reports.api.views import TelegramReportsWebhookView


urlpatterns = [
    path("webhook/", TelegramReportsWebhookView.as_view(), name="telegram-reports-webhook"),
]

