import logging

from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.api.pos.serializers import (
    PosLoginSerializer,
    PosRestaurantCodeSerializer,
    PosRestaurantContextSerializer,
    PosSessionSerializer,
)
from apps.users.services import AuthSessionService
from common.api.permissions import EndpointRBACPermission
from common.api.throttling import PinLoginRateThrottle

logger = logging.getLogger(__name__)


class PosRestaurantCodeView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PosRestaurantCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = serializer.validated_data['restaurant']
        return Response(PosRestaurantContextSerializer(restaurant).data)


class PosPinLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PinLoginRateThrottle]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        serializer = PosLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            logger.warning('POS login failed', extra={'ui_channel': 'pos', 'client_ip': request.META.get('REMOTE_ADDR')})
            raise
        user = serializer.validated_data['user']
        restaurant = serializer.validated_data['restaurant']
        token, session = self.auth_session_service_class().issue(user=user, request=request, surface='pos')
        return Response(PosSessionSerializer({'token': token.key, 'user': user, 'session': session, 'restaurant': restaurant}).data)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    auth_session_service_class = AuthSessionService

    def post(self, request):
        self.auth_session_service_class().revoke(request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PosMeView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request):
        return Response(PosSessionSerializer({'token': '', 'user': request.user}).data)

__all__ = ['LogoutView', 'PosMeView', 'PosPinLoginView', 'PosRestaurantCodeView']
