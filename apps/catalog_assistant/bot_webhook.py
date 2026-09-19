import secrets
from django.conf import settings
from django.db import transaction
from django_q.tasks import async_task
from rest_framework import permissions
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import ManagementBotUpdate


class ManagementBotWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser]  # Telegram uses snake_case, not admin camel-case parsing.
    renderer_classes = [JSONRenderer]

    def post(self, request):
        expected = getattr(settings, 'MANAGEMENT_BOT_WEBHOOK_SECRET', '')
        supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not expected or not secrets.compare_digest(expected, supplied):
            return Response({'ok': False}, status=403)
        payload = request.data
        if not isinstance(payload, dict) or type(payload.get('update_id')) is not int:
            return Response({'ok': False}, status=400)
        update, _ = ManagementBotUpdate.objects.get_or_create(update_id=payload['update_id'], defaults={'payload': payload})
        if update.status in ('done', 'rejected'):
            return Response({'ok': True})
        try:
            async_task('apps.catalog_assistant.bot_tasks.process_update', str(update.pk), timeout=150)
        except Exception:
            return Response({'ok': False}, status=503)  # Telegram retries; durable row survives.
        return Response({'ok': True})
