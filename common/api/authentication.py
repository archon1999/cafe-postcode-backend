from datetime import timedelta

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from apps.users.models import AuthSession


class ExpiringSessionTokenAuthentication(BaseAuthentication):
    """DRF token auth backed by a revocable, expiring and surface-bound session."""

    keyword = 'Token'

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth:
            return None
        if auth[0].lower() != self.keyword.lower().encode():
            return None
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed('Invalid token header.')

        try:
            key = auth[1].decode()
        except UnicodeError as error:
            raise exceptions.AuthenticationFailed('Invalid token header.') from error

        now = timezone.now()
        session = AuthSession.objects.select_related('user').filter(
            token_key_hash=AuthSession.build_token_key_hash(key),
            status=AuthSession.Status.ACTIVE,
            expires_at__gt=now,
        ).first()
        if session is None:
            raise exceptions.AuthenticationFailed('Authentication session is expired or revoked.')

        if not session.user.is_active:
            raise exceptions.AuthenticationFailed('User inactive or deleted.')

        expected_surface = self._surface_for_path(request.path)
        if expected_surface and session.surface != expected_surface:
            raise exceptions.AuthenticationFailed('Authentication token is not valid for this application.')

        if session.last_seen_at is None or session.last_seen_at < now - timedelta(minutes=5):
            AuthSession.objects.filter(pk=session.pk).update(last_seen_at=now, updated_at=now)
        return session.user, session

    def authenticate_header(self, request):
        return self.keyword

    @staticmethod
    def _surface_for_path(path: str) -> str | None:
        if path.startswith('/api/v1/pos/'):
            return AuthSession.Surface.POS
        if path.startswith('/api/v1/dashboard/'):
            return AuthSession.Surface.DASHBOARD
        if path.startswith('/api/v1/admin/'):
            return AuthSession.Surface.ADMIN
        return None
