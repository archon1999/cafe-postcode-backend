from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from apps.users.models import AdminRefreshFamily, AuthSession
from apps.devices.models import SecurityEvent
from apps.devices.security import record_security_event
from apps.devices.authentication import DeviceAuthenticationFailed, authenticate_device_request
from apps.devices.migration_window import legacy_cohort_eligible, legacy_unbound_pos_session_auth_enabled


class AdminSessionLocked(exceptions.APIException):
    status_code = 423
    default_code = 'session_locked'
    default_detail = 'Admin session is locked.'


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
        session = AuthSession.objects.select_related(
            'user',
            'device__restaurant',
            'restaurant',
            'refresh_family',
        ).filter(
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

        if session.surface == AuthSession.Surface.ADMIN:
            self._authenticate_admin_family(request=request, session=session, now=now)

        if (
            session.surface == AuthSession.Surface.POS
            and session.device_id is None
            and (
                not legacy_unbound_pos_session_auth_enabled(now=now)
                or not legacy_cohort_eligible(created_at=session.created_at, now=now)
            )
        ):
            AuthSession.objects.filter(pk=session.pk, status=AuthSession.Status.ACTIVE).update(
                status=AuthSession.Status.REVOKED,
                revoked_at=now,
                updated_at=now,
            )
            record_security_event(
                event_type='LEGACY_POS_SESSION_REJECTED',
                request=request,
                actor=session.user,
                auth_session=session,
                severity=SecurityEvent.Severity.HIGH,
                result='device_binding_required',
            )
            raise DeviceAuthenticationFailed(
                'device_proof_required',
                'POS session is not bound to an approved device.',
            )

        if session.locked_at is not None and not (
            request.path.endswith('/auth/lock/')
            or request.path.endswith('/auth/unlock/')
            or request.path.endswith('/auth/logout/')
        ):
            raise exceptions.AuthenticationFailed({'code': 'session_locked', 'detail': 'POS session is locked.'})

        if session.device_id is not None:
            expected_types = None
            if session.surface == AuthSession.Surface.POS:
                from apps.devices.models import Device

                expected_types = [Device.Type.POS_TERMINAL]
            device = authenticate_device_request(
                request,
                expected_device=session.device,
                expected_types=expected_types,
            )
            if session.restaurant_id != device.restaurant_id:
                raise DeviceAuthenticationFailed(
                    'device_restaurant_mismatch',
                    'Device restaurant does not match the authenticated session.',
                )
            if session.surface == AuthSession.Surface.POS:
                user_restaurant = session.user.get_restaurant_scope()
                if user_restaurant is None or user_restaurant.pk != session.restaurant_id:
                    raise DeviceAuthenticationFailed(
                        'device_restaurant_mismatch',
                        'User, device and session restaurant scopes do not match.',
                    )

        if session.last_seen_at is None or session.last_seen_at < now - timedelta(minutes=5):
            AuthSession.objects.filter(pk=session.pk).update(last_seen_at=now, updated_at=now)
        return session.user, session

    @staticmethod
    def _authenticate_admin_family(*, request, session: AuthSession, now):
        if session.refresh_family_id is None:
            AuthSession.objects.filter(pk=session.pk).update(
                status=AuthSession.Status.REVOKED,
                revoked_at=now,
                updated_at=now,
            )
            raise exceptions.AuthenticationFailed(
                {'code': 'admin_session_upgrade_required', 'detail': 'Sign in again to upgrade this admin session.'}
            )

        auth_error = None
        with transaction.atomic():
            family = (
                AdminRefreshFamily.objects.select_for_update()
                .select_related('user')
                .filter(pk=session.refresh_family_id)
                .first()
            )
            if (
                family is None
                or family.status != AdminRefreshFamily.Status.ACTIVE
                or family.absolute_expires_at <= now
            ):
                AuthSession.objects.filter(refresh_family_id=session.refresh_family_id).update(
                    status=AuthSession.Status.REVOKED,
                    revoked_at=now,
                    updated_at=now,
                )
                auth_error = exceptions.AuthenticationFailed(
                    {'code': 'refresh_expired', 'detail': 'Admin refresh session is expired or revoked.'},
                )
            elif (
                settings.ADMIN_MFA_REQUIRED
                and session.user.is_superuser
                and (family.mfa_verified_at is None or session.mfa_verified_at is None)
            ):
                auth_error = exceptions.AuthenticationFailed(
                    {'code': 'mfa_required', 'detail': 'MFA verification is required.'},
                )
            elif family.locked_at is not None or (
                settings.ADMIN_IDLE_LOCK_SECONDS > 0
                and family.last_activity_at <= now - timedelta(seconds=settings.ADMIN_IDLE_LOCK_SECONDS)
            ):
                if family.locked_at is None:
                    family.locked_at = now
                    family.save(update_fields=['locked_at', 'updated_at'])
                    AuthSession.objects.filter(
                        refresh_family=family,
                        status=AuthSession.Status.ACTIVE,
                    ).update(locked_at=now, updated_at=now)
                    record_security_event(
                        event_type='ADMIN_SESSION_LOCKED',
                        request=request,
                        actor=family.user,
                        auth_session=session,
                        severity=SecurityEvent.Severity.MEDIUM,
                        result='idle',
                    )
                auth_error = AdminSessionLocked(
                    {
                        'code': 'session_locked',
                        'detail': 'Admin session is locked.',
                        'locked_at': family.locked_at,
                    }
                )
            elif request.headers.get('X-Admin-User-Activity') == '1':
                family.last_activity_at = now
                family.save(update_fields=['last_activity_at', 'updated_at'])
        if auth_error is not None:
            raise auth_error

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
        if path.startswith('/api/v1/local-agent/'):
            # Browser-facing Local Agent operations are part of the admin
            # surface. Machine Agent requests use their own signed/legacy
            # authentication and do not present a `Token` session.
            return AuthSession.Surface.ADMIN
        return None
