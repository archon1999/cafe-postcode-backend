import logging
from secrets import token_urlsafe
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.users.helpers import get_auth_session_model
from common.api.client_ip import get_client_ip

logger = logging.getLogger(__name__)


class AuthSessionService:
    @transaction.atomic
    def issue(
        self,
        *,
        user,
        request,
        surface: str,
        device=None,
        restaurant=None,
        refresh_family=None,
        mfa_verified_at=None,
    ):
        token_key = token_urlsafe(48)
        session = self._create_session(
            user=user,
            token_key=token_key,
            request=request,
            surface=surface,
            device=device,
            restaurant=restaurant,
            refresh_family=refresh_family,
            mfa_verified_at=mfa_verified_at,
        )
        logger.info(
            'Authentication session issued',
            extra={'user_id': str(user.pk), 'session_id': str(session.pk)},
        )
        return token_key, session

    def revoke(self, *, request):
        auth_session_model = get_auth_session_model()
        session = request.auth if isinstance(request.auth, auth_session_model) else None
        if session is None:
            return None

        session = auth_session_model.objects.filter(
            pk=session.pk,
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

        return session

    def _create_session(
        self,
        *,
        user,
        token_key: str,
        request,
        surface: str,
        device=None,
        restaurant=None,
        refresh_family=None,
        mfa_verified_at=None,
    ):
        auth_session_model = get_auth_session_model()
        now = timezone.now()
        return auth_session_model.objects.create(
            token_key_hash=auth_session_model.build_token_key_hash(token_key),
            user=user,
            device=device,
            restaurant=restaurant,
            refresh_family=refresh_family,
            mfa_verified_at=mfa_verified_at,
            surface=surface,
            expires_at=now + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS[surface]),
            client_ip=get_client_ip(request),
            user_agent=request.headers.get('User-Agent', '')[:255],
            status=auth_session_model.Status.ACTIVE,
            last_seen_at=now,
        )
