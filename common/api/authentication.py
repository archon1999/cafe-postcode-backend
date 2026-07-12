from datetime import timedelta

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

from apps.users.models import AuthSession


class ExpiringSessionTokenAuthentication(TokenAuthentication):
    """DRF token auth backed by a revocable, expiring and surface-bound session."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        now = timezone.now()
        session = AuthSession.objects.filter(
            token_key_hash=AuthSession.build_token_key_hash(key),
            user=user,
            status=AuthSession.Status.ACTIVE,
            expires_at__gt=now,
        ).first()
        if session is None:
            raise exceptions.AuthenticationFailed('Authentication session is expired or revoked.')

        expected_surface = self._surface_for_path(getattr(self, '_request_path', ''))
        if expected_surface and session.surface != expected_surface:
            raise exceptions.AuthenticationFailed('Authentication token is not valid for this application.')

        if session.last_seen_at is None or session.last_seen_at < now - timedelta(minutes=5):
            AuthSession.objects.filter(pk=session.pk).update(last_seen_at=now, updated_at=now)
        return user, token

    def authenticate(self, request):
        self._request_path = request.path
        try:
            return super().authenticate(request)
        finally:
            self._request_path = ''

    @staticmethod
    def _surface_for_path(path: str) -> str | None:
        if path.startswith('/api/v1/pos/'):
            return AuthSession.Surface.POS
        if path.startswith('/api/v1/dashboard/'):
            return AuthSession.Surface.DASHBOARD
        if path.startswith('/api/v1/admin/'):
            return AuthSession.Surface.ADMIN
        return None
