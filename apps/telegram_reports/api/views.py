import logging
import secrets

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.telegram_reports.handler import TelegramUpdateHandler
from apps.telegram_reports.models import TelegramProcessedUpdate


logger = logging.getLogger(__name__)


class TelegramReportsWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    handler_class = TelegramUpdateHandler

    def post(self, request):
        expected_secret = settings.TELEGRAM_REPORTS_WEBHOOK_SECRET
        received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if expected_secret and not secrets.compare_digest(received_secret, expected_secret):
            return Response({"ok": False}, status=status.HTTP_403_FORBIDDEN)

        update = request.data if isinstance(request.data, dict) else {}
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return Response({"ok": False}, status=status.HTTP_400_BAD_REQUEST)

        processed, created = TelegramProcessedUpdate.objects.get_or_create(update_id=update_id)
        if not created:
            return Response({"ok": True})

        try:
            self.handler_class().handle(update)
        except Exception as error:  # noqa: BLE001 - Telegram must receive a stable acknowledgement.
            logger.exception("Telegram reports update processing failed", extra={"update_id": update_id})
            processed.status = TelegramProcessedUpdate.Status.FAILED
            processed.error = str(error)[:2000]
            processed.save(update_fields=("status", "error", "updated_at"))
        else:
            processed.status = TelegramProcessedUpdate.Status.SUCCEEDED
            processed.save(update_fields=("status", "updated_at"))
        return Response({"ok": True})
