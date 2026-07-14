import logging

from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.lan import private_lan_endpoints
from apps.local_agents.models import LocalAgent
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.users.api.pos.serializers import (
    PosLoginSerializer,
    PosRestaurantCodeSerializer,
    PosRestaurantContextSerializer,
    PosSessionSerializer,
    PosTransportDiscoverySerializer,
)
from apps.users.services import AuthSessionService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.api.throttling import PinLoginRateThrottle

logger = logging.getLogger(__name__)


def _issue_coordinator(*, restaurant, terminal_id='', terminal_name=''):
    try:
        result = LocalAgentCommandService().execute(
            restaurant=restaurant,
            command_type='edge.terminal.issue',
            payload={
                'terminalId': str(terminal_id or '').strip(),
                'terminalName': str(terminal_name or '').strip() or 'POS terminal',
            },
            timeout_seconds=6,
        )
        edge_token = str(result.get('edgeToken') or '')
        if not edge_token.startswith('ept_'):
            return None
        agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).only('lan_endpoints').first()
        return {
            'restaurantId': str(restaurant.id),
            'edgeToken': edge_token,
            'coordinatorUrls': private_lan_endpoints(agent.lan_endpoints or []) if agent else [],
        }
    except (LocalAgentUnavailableError, LocalAgentCommandError):
        return None


class PosRestaurantCodeView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PosRestaurantCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = serializer.validated_data['restaurant']
        payload = dict(PosRestaurantContextSerializer(restaurant).data)
        payload['coordinator'] = _issue_coordinator(
            restaurant=restaurant,
            terminal_id=serializer.validated_data.get('terminal_id', ''),
            terminal_name=serializer.validated_data.get('terminal_name', ''),
        )
        return Response(payload)


class PosTransportDiscoveryView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request):
        serializer = PosTransportDiscoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = get_request_restaurant(request)
        return Response(
            {
                'restaurantId': str(restaurant.id),
                'coordinator': _issue_coordinator(
                    restaurant=restaurant,
                    terminal_id=serializer.validated_data.get('terminal_id', ''),
                    terminal_name=serializer.validated_data.get('terminal_name', ''),
                ),
            }
        )


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
        return Response(PosSessionSerializer({'token': token, 'user': user, 'session': session, 'restaurant': restaurant}).data)


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

__all__ = ['LogoutView', 'PosMeView', 'PosPinLoginView', 'PosRestaurantCodeView', 'PosTransportDiscoveryView']
