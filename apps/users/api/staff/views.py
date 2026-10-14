import hashlib

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import AuthSession, User
from apps.users.services.staff_auth import StaffAuthError, StaffAuthService, staff_user_is_eligible
from common.api.client_ip import get_client_ip
from common.api.throttling import LoginRateThrottle


def _error(exc):
    return Response({'code': exc.code, 'detail': exc.detail}, status=exc.http_status)


def _require_origin(request):
    if request.headers.get('Origin', '') not in settings.STAFF_AUTH_ALLOWED_ORIGINS:
        raise StaffAuthError('origin_not_allowed', 'Request Origin is not allowed.', 403)


def _user_payload(user):
    restaurant = user.get_restaurant_scope()
    return {
        'id': user.pk,
        'full_name': user.full_name,
        'username': user.username,
        'restaurant_id': restaurant.pk if restaurant else None,
        'restaurant_name': restaurant.name if restaurant else '',
        'role_code': user.role_code,
        'permissions': user.permission_codes,
    }


def _credentials_response(bundle):
    response = Response({
        'access_token': bundle.access_token,
        'access_expires_at': bundle.access_session.expires_at,
        'refresh_expires_at': bundle.refresh_family.absolute_expires_at,
        'user': _user_payload(bundle.refresh_family.user),
    })
    response.set_cookie(
        settings.STAFF_REFRESH_COOKIE_NAME,
        bundle.refresh_token,
        max_age=max(0, int((bundle.refresh_family.absolute_expires_at - timezone.now()).total_seconds())),
        path='/',
        secure=settings.STAFF_REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite='Strict',
    )
    response['Cache-Control'] = 'no-store'
    return response


def _clear_cookie(response):
    response.set_cookie(
        settings.STAFF_REFRESH_COOKIE_NAME,
        value='',
        max_age=0,
        path='/',
        secure=settings.STAFF_REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite='Strict',
    )
    response['Cache-Control'] = 'no-store'
    return response


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200)
    password = serializers.CharField(min_length=8, max_length=128, trim_whitespace=False)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False)


class StaffInviteAcceptView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        try:
            _require_origin(request)
            serializer = InviteAcceptSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            bundle = StaffAuthService().accept_invite(
                raw_token=serializer.validated_data['token'],
                password=serializer.validated_data['password'],
                request=request,
            )
        except StaffAuthError as exc:
            return _error(exc)
        return _credentials_response(bundle)


class StaffLoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        try:
            _require_origin(request)
        except StaffAuthError as exc:
            return _error(exc)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username'].strip()
        key = 'staff-login-failures:' + hashlib.sha256(
            f'{username.casefold()}\n{get_client_ip(request) or "unknown"}'.encode('utf-8')
        ).hexdigest()
        if int(cache.get(key, 0) or 0) >= settings.STAFF_LOGIN_MAX_FAILURES:
            return _error(StaffAuthError('login_locked', 'Too many login attempts.', 429))
        user = User.objects.select_related('role', 'restaurant_profile__restaurant', 'employee_profile').filter(
            username=username,
        ).first()
        if not staff_user_is_eligible(user) or not user.has_usable_password() or not user.check_password(
            serializer.validated_data['password']
        ):
            count = int(cache.get(key, 0) or 0) + 1
            cache.set(key, count, settings.STAFF_LOGIN_LOCKOUT_SECONDS)
            return _error(StaffAuthError(
                'login_locked' if count >= settings.STAFF_LOGIN_MAX_FAILURES else 'invalid_credentials',
                'Invalid credentials.' if count < settings.STAFF_LOGIN_MAX_FAILURES else 'Too many login attempts.',
                429 if count >= settings.STAFF_LOGIN_MAX_FAILURES else 401,
            ))
        cache.delete(key)
        return _credentials_response(StaffAuthService().issue_credentials(user=user, request=request))


class StaffRefreshView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            _require_origin(request)
            bundle = StaffAuthService().rotate_refresh(
                raw_token=request.COOKIES.get(settings.STAFF_REFRESH_COOKIE_NAME, ''),
                request=request,
            )
        except StaffAuthError as exc:
            response = _error(exc)
            return response if exc.code == 'refresh_raced' else _clear_cookie(response)
        return _credentials_response(bundle)


class StaffLogoutView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            _require_origin(request)
        except StaffAuthError as exc:
            return _error(exc)
        StaffAuthService().revoke_by_cookie(raw_token=request.COOKIES.get(settings.STAFF_REFRESH_COOKIE_NAME, ''))
        return _clear_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class StaffMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not isinstance(request.auth, AuthSession) or request.auth.surface != AuthSession.Surface.STAFF:
            return Response({'code': 'staff_session_required'}, status=403)
        response = Response({'user': _user_payload(request.user)})
        response['Cache-Control'] = 'no-store'
        return response
