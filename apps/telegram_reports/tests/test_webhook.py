from django.test import override_settings
from rest_framework.test import APITestCase

from apps.telegram_reports.models import TelegramProcessedUpdate


class StubHandler:
    calls = []

    def handle(self, update):
        self.__class__.calls.append(update)


@override_settings(TELEGRAM_REPORTS_WEBHOOK_SECRET="test-secret")
class TelegramWebhookTests(APITestCase):
    def setUp(self):
        StubHandler.calls = []

    def test_webhook_checks_secret_and_processes_update_once(self):
        from apps.telegram_reports.api.views import TelegramReportsWebhookView

        original = TelegramReportsWebhookView.handler_class
        TelegramReportsWebhookView.handler_class = StubHandler
        self.addCleanup(setattr, TelegramReportsWebhookView, "handler_class", original)
        payload = {"update_id": 8123, "message": {"text": "/start"}}

        denied = self.client.post("/api/v1/telegram-reports/webhook/", payload, format="json")
        accepted = self.client.post(
            "/api/v1/telegram-reports/webhook/",
            payload,
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
        )
        duplicate = self.client.post(
            "/api/v1/telegram-reports/webhook/",
            payload,
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-secret",
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(len(StubHandler.calls), 1)
        processed = TelegramProcessedUpdate.objects.get(update_id=8123)
        self.assertEqual(processed.status, TelegramProcessedUpdate.Status.SUCCEEDED)

