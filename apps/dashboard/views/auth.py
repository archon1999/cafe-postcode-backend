import logging

from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.serializers import OwnerDashboardLoginSerializer, OwnerDashboardUserSerializer
from apps.users.api.admin.serializers import AuthSessionSerializer
from apps.users.services import AuthSessionService
from common.api.permissions import EndpointRBACPermission
from common.api.throttling import LoginRateThrottle

logger = logging.getLogger(__name__)


class DashboardAuthLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        serializer = OwnerDashboardLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning(
                'Dashboard login failed',
                extra={'ui_channel': 'dashboard', 'client_ip': request.META.get('REMOTE_ADDR')},
            )
            raise
        user = serializer.validated_data['user']
        token, session = self.auth_session_service_class().issue(user=user, request=request)
        return Response(
            {'token': token.key, 'user': OwnerDashboardUserSerializer(user).data, 'session': AuthSessionSerializer(session).data}
        )


class DashboardAuthLogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        self.auth_session_service_class().revoke(request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DashboardAuthMeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        return Response(OwnerDashboardUserSerializer(request.user).data)
