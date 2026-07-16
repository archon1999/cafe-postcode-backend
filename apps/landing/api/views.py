import html
import logging

import httpx
from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from apps.landing.api.serializers import LandingLeadSerializer

logger = logging.getLogger(__name__)


class LandingLeadView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = 'submit'

    def post(self, request):
        serializer = LandingLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_LEADS_CHAT_ID:
            logger.error('Landing lead submission is not configured.')
            return Response({'ok': False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        data = serializer.validated_data
        try:
            with httpx.Client(
                proxy=settings.TELEGRAM_PROXY_URL or None,
                timeout=settings.TELEGRAM_TIMEOUT,
            ) as client:
                response = client.post(
                    f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
                    json={
                        'chat_id': settings.TELEGRAM_LEADS_CHAT_ID,
                        'text': self._build_message(data),
                        'parse_mode': 'HTML',
                        'disable_web_page_preview': True,
                    },
                )
            response.raise_for_status()
            if response.json().get('ok') is not True:
                raise ValueError('Telegram rejected the message.')
        except (httpx.HTTPError, ValueError):
            logger.exception('Unable to send landing lead to Telegram.')
            return Response({'ok': False}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({'ok': True}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _build_message(data: dict[str, str]) -> str:
        def safe(value: str) -> str:
            return html.escape(value, quote=False)

        lines = [
            '<b>🔥 Yangi murojaat — PosCode FastFOOD</b>',
            '',
            f'👤 <b>Ism:</b> {safe(data["name"])}',
            f'📞 <b>Telefon:</b> {safe(data["phone"])}',
        ]
        if shop := data.get('shop'):
            lines.append(f'🏪 <b>Shaxobcha:</b> {safe(shop)}')
        lines.extend(
            [
                f'📦 <b>Tarif:</b> {safe(data.get("plan") or "Umumiy")}',
                f'🕒 <b>Vaqt:</b> {timezone.localtime().strftime("%d/%m/%Y, %H:%M:%S")}',
            ]
        )
        return '\n'.join(lines)
