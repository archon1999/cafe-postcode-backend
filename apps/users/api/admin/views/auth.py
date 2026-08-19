import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.models import SecurityEvent
from apps.devices.security import get_client_ip, record_security_event
from apps.users.api.admin.serializers import (
    AdminLoginSerializer,
    AdminUnlockSerializer,
    AuthSessionSerializer,
    MFAChallengeTokenSerializer,
    MFACodeSerializer,
    MFAStepUpSerializer,
    SessionUserSerializer,
)
from apps.users.models import AuthSession, User
from apps.users.services import AdminAuthError, AdminAuthService
from common.api.admin_permissions import AdminAllowAnyMixin, AdminAuthenticatedMixin
from common.api.throttling import LoginRateThrottle


logger = logging.getLogger(__name__)


def _error_response(error: AdminAuthError):
    return Response({'code': error.code, 'detail': error.detail}, status=error.http_status)


def _require_exact_admin_origin(request):
    origin = request.headers.get('Origin', '')
    if origin not in set(settings.ADMIN_AUTH_ALLOWED_ORIGINS):
        record_security_event(
            event_type='ADMIN_AUTH_ORIGIN_REJECTED',
            request=request,
            severity=SecurityEvent.Severity.HIGH,
            result='rejected',
            metadata={'origin': origin[:300]},
        )
        raise AdminAuthError('origin_not_allowed', 'Request Origin is not allowed.', http_status=403)


def _set_refresh_cookie(response: Response, bundle):
    remaining = max(0, int((bundle.refresh_family.absolute_expires_at - timezone.now()).total_seconds()))
    response.set_cookie(
        settings.ADMIN_REFRESH_COOKIE_NAME,
        bundle.refresh_token,
        max_age=remaining,
        path='/',
        secure=True,
        httponly=True,
        samesite='Strict',
    )
    return response


def _clear_refresh_cookie(response: Response):
    response.set_cookie(
        settings.ADMIN_REFRESH_COOKIE_NAME,
        value='',
        max_age=0,
        path='/',
        secure=True,
        httponly=True,
        samesite='Strict',
    )
    return response


def _credential_response(bundle, *, recovery_codes=None):
    payload = {
        'status': 'authenticated',
        'access_token': bundle.access_token,
        'access_expires_at': bundle.access_session.expires_at,
        'refresh_expires_at': bundle.refresh_family.absolute_expires_at,
        'user': SessionUserSerializer(bundle.refresh_family.user).data,
        'session': AuthSessionSerializer(bundle.access_session).data,
    }
    if recovery_codes is not None:
        payload['recovery_codes'] = recovery_codes
    return _set_refresh_cookie(Response(payload), bundle)


def _login_cache_key(username: str, request) -> str:
    raw = f'{username.strip().casefold()}\n{get_client_ip(request) or "unknown"}'
    return f'admin-login-failures:{hashlib.sha256(raw.encode("utf-8")).hexdigest()}'


def _login_failure_count(username: str, request) -> int:
    return int(cache.get(_login_cache_key(username, request), 0) or 0)


def _record_login_failure(username: str, request) -> int:
    key = _login_cache_key(username, request)
    count = _login_failure_count(username, request) + 1
    cache.set(key, count, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
    actor = User.objects.filter(username=username).first()
    locked = count >= settings.ADMIN_LOGIN_MAX_FAILURES
    record_security_event(
        event_type='ADMIN_LOGIN_LOCKED_OUT' if locked else 'ADMIN_LOGIN_FAILED',
        request=request,
        actor=actor,
        severity=SecurityEvent.Severity.HIGH if locked else SecurityEvent.Severity.MEDIUM,
        result='locked' if locked else 'failed',
        metadata={'failureCount': count},
    )
    return count


class AdminLoginView(AdminAllowAnyMixin, APIView):
    throttle_classes = [LoginRateThrottle]
    auth_service_class = AdminAuthService

    def post(self, request):
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        username = str(request.data.get('username') or '')
        if _login_failure_count(username, request) >= settings.ADMIN_LOGIN_MAX_FAILURES:
            record_security_event(
                event_type='ADMIN_LOGIN_LOCKED_OUT',
                request=request,
                severity=SecurityEvent.Severity.HIGH,
                result='blocked',
            )
            return Response(
                {'code': 'login_locked', 'detail': 'Too many failed login attempts. Try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        serializer = AdminLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            count = _record_login_failure(username, request)
            code = 'login_locked' if count >= settings.ADMIN_LOGIN_MAX_FAILURES else 'invalid_credentials'
            http_status = status.HTTP_429_TOO_MANY_REQUESTS if code == 'login_locked' else status.HTTP_400_BAD_REQUEST
            return Response({'code': code, 'detail': str(_('Invalid credentials.'))}, status=http_status)
        cache.delete(_login_cache_key(username, request))
        user = serializer.validated_data['user']
        service = self.auth_service_class()
        if user.is_superuser and settings.ADMIN_MFA_REQUIRED:
            challenge_token, challenge = service.issue_mfa_challenge(user=user, request=request)
            response_status = 'mfa_required' if challenge.kind == challenge.Kind.LOGIN else 'mfa_enrollment_required'
            return Response(
                {
                    'status': response_status,
                    'challenge_token': challenge_token,
                    'challenge_expires_at': challenge.expires_at,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        try:
            bundle = service.issue_credentials(user=user, request=request)
        except AdminAuthError as error:
            return _error_response(error)
        record_security_event(
            event_type='ADMIN_LOGIN_SUCCEEDED',
            request=request,
            actor=user,
            auth_session=bundle.access_session,
            severity=SecurityEvent.Severity.INFO,
            result='success',
        )
        return _credential_response(bundle)


class AdminRefreshView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        try:
            _require_exact_admin_origin(request)
            bundle = self.auth_service_class().rotate_refresh(
                raw_token=request.COOKIES.get(settings.ADMIN_REFRESH_COOKIE_NAME, ''),
                request=request,
            )
        except AdminAuthError as error:
            response = _error_response(error)
            if error.code not in {'refresh_race', 'session_locked'}:
                _clear_refresh_cookie(response)
            return response
        return _credential_response(bundle)


class LogoutView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        self.auth_service_class().revoke_family_by_cookie(
            raw_token=request.COOKIES.get(settings.ADMIN_REFRESH_COOKIE_NAME, ''),
            request=request,
        )
        return _clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class AdminLockView(AdminAuthenticatedMixin, APIView):
    auth_service_class = AdminAuthService

    def post(self, request):
        session = request.auth if isinstance(request.auth, AuthSession) else None
        if session is None:
            return Response({'code': 'admin_session_required', 'detail': 'Admin session is required.'}, status=401)
        try:
            family = self.auth_service_class().lock(access_session=session, request=request)
        except AdminAuthError as error:
            return _error_response(error)
        return Response({'status': 'locked', 'locked_at': family.locked_at})


class AdminUnlockView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        serializer = AdminUnlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bundle = self.auth_service_class().unlock(
                raw_token=request.COOKIES.get(settings.ADMIN_REFRESH_COOKIE_NAME, ''),
                password=serializer.validated_data['password'],
                request=request,
            )
        except AdminAuthError as error:
            return _error_response(error)
        return _credential_response(bundle)


class MFAEnrollmentStartView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        if not settings.ADMIN_MFA_REQUIRED:
            return Response({'code': 'mfa_disabled', 'detail': 'MFA is disabled.'}, status=410)
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        serializer = MFAChallengeTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = self.auth_service_class().start_enrollment(
                challenge_token=serializer.validated_data['challenge_token'],
                request=request,
            )
        except AdminAuthError as error:
            return _error_response(error)
        return Response(payload)


class MFAEnrollmentConfirmView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        if not settings.ADMIN_MFA_REQUIRED:
            return Response({'code': 'mfa_disabled', 'detail': 'MFA is disabled.'}, status=410)
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get('recovery_code'):
            return Response({'code': 'recovery_not_allowed', 'detail': 'Recovery cannot confirm enrollment.'}, status=400)
        try:
            bundle, recovery_codes = self.auth_service_class().confirm_enrollment(
                challenge_token=serializer.validated_data['challenge_token'],
                code=serializer.validated_data['code'],
                request=request,
            )
        except AdminAuthError as error:
            return _error_response(error)
        return _credential_response(bundle, recovery_codes=recovery_codes)


class MFAChallengeView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    auth_service_class = AdminAuthService

    def post(self, request):
        if not settings.ADMIN_MFA_REQUIRED:
            return Response({'code': 'mfa_disabled', 'detail': 'MFA is disabled.'}, status=410)
        try:
            _require_exact_admin_origin(request)
        except AdminAuthError as error:
            return _error_response(error)
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bundle = self.auth_service_class().complete_mfa_challenge(
                challenge_token=serializer.validated_data['challenge_token'],
                code=serializer.validated_data.get('code', ''),
                recovery_code=serializer.validated_data.get('recovery_code', ''),
                request=request,
            )
        except AdminAuthError as error:
            return _error_response(error)
        return _credential_response(bundle)


class MFAStepUpView(AdminAuthenticatedMixin, APIView):
    auth_service_class = AdminAuthService

    def post(self, request):
        if not settings.ADMIN_MFA_REQUIRED:
            return Response({'code': 'mfa_disabled', 'detail': 'MFA is disabled.'}, status=410)
        serializer = MFAStepUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = request.auth if isinstance(request.auth, AuthSession) else None
        if session is None:
            return Response({'code': 'admin_session_required', 'detail': 'Admin session is required.'}, status=401)
        try:
            verified_at = self.auth_service_class().step_up(
                access_session=session,
                request=request,
                code=serializer.validated_data.get('code', ''),
                recovery_code=serializer.validated_data.get('recovery_code', ''),
            )
        except AdminAuthError as error:
            return _error_response(error)
        return Response({'status': 'verified', 'mfa_verified_at': verified_at})


class MeView(AdminAuthenticatedMixin, APIView):
    def get(self, request):
        return Response(SessionUserSerializer(request.user).data)


__all__ = [
    'AdminLockView',
    'AdminLoginView',
    'AdminRefreshView',
    'AdminUnlockView',
    'LogoutView',
    'MeView',
    'MFAChallengeView',
    'MFAEnrollmentConfirmView',
    'MFAEnrollmentStartView',
    'MFAStepUpView',
]
