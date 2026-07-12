import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.users.helpers import get_auth_session_model

logger = logging.getLogger(__name__)


class AuthSessionService:
    @transaction.atomic
    def issue(self, *, user, request, surface: str):
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        session = self._upsert_session(user=user, token_key=token.key, request=request, surface=surface)
        logger.info(
            'Authentication session issued',
            extra={'user_id': str(user.pk), 'session_id': str(session.pk)},
        )
        return token, session

    def revoke(self, *, request):
        auth_session_model = get_auth_session_model()
        token = request.auth if isinstance(request.auth, Token) else None
        if token is None and getattr(request.user, 'is_authenticated', False):
            token = Token.objects.filter(user=request.user).first()

        if token is None:
            return None

        session = auth_session_model.objects.filter(
            token_key_hash=auth_session_model.build_token_key_hash(token.key),
            status=auth_session_model.Status.ACTIVE,
        ).first()
        if session is not None:
            revoked_at = timezone.now()
            session.status = auth_session_model.Status.REVOKED
            session.revoked_at = revoked_at
            session.last_seen_at = revoked_at
            session.save(update_fields=['status', 'revoked_at', 'last_seen_at', 'updated_at'])
            logger.info(
                'Authentication session revoked',
                extra={'user_id': str(session.user_id), 'session_id': str(session.pk)},
            )

        token.delete()
        return session

    def _upsert_session(self, *, user, token_key: str, request, surface: str):
        auth_session_model = get_auth_session_model()
        now = timezone.now()
        session, _ = auth_session_model.objects.update_or_create(
            token_key_hash=auth_session_model.build_token_key_hash(token_key),
            defaults={
                'user': user,
                'surface': surface,
                'expires_at': now + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS[surface]),
                'client_ip': self._get_client_ip(request),
                'user_agent': request.headers.get('User-Agent', '')[:255],
                'status': auth_session_model.Status.ACTIVE,
                'revoked_at': None,
                'last_seen_at': now,
            },
        )
        auth_session_model.objects.filter(user=user).exclude(pk=session.pk).filter(
            status=auth_session_model.Status.ACTIVE
        ).update(
            status=auth_session_model.Status.REVOKED,
            revoked_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        return session

    @staticmethod
    def _get_client_ip(request) -> str | None:
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip() or None
        return request.META.get('REMOTE_ADDR')
