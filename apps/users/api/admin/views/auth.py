import logging

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.api.admin.serializers import AdminLoginSerializer, AuthSessionSerializer, SessionUserSerializer
from apps.users.services import AuthSessionService
from common.api.admin_permissions import AdminAllowAnyMixin, AdminAuthenticatedMixin
from common.api.throttling import LoginRateThrottle

logger = logging.getLogger(__name__)


class AdminLoginView(AdminAllowAnyMixin, APIView):
    throttle_classes = [LoginRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning('Admin login failed', extra={'ui_channel': 'admin', 'client_ip': request.META.get('REMOTE_ADDR')})
            raise
        user = serializer.validated_data['user']
        token, session = self.auth_session_service_class().issue(user=user, request=request, surface='admin')
        return Response({'token': token.key, 'user': SessionUserSerializer(user).data, 'session': AuthSessionSerializer(session).data})


class LogoutView(AdminAuthenticatedMixin, APIView):
    auth_session_service_class = AuthSessionService

    def post(self, request):
        self.auth_session_service_class().revoke(request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(AdminAuthenticatedMixin, APIView):
    def get(self, request):
        return Response(SessionUserSerializer(request.user).data)

__all__ = ['AdminLoginView', 'LogoutView', 'MeView']
