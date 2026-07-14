from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgent
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


def _offline_status(agent):
    return {
        'agent': {
            'online': False,
            'version': agent.version if agent else '',
            'restaurantId': str(agent.restaurant_id) if agent else '',
        },
        'backend': {'online': True, 'offlineMode': False},
        'sync': {'ready': False, 'pendingOutbox': 0, 'failedOutbox': 0, 'schemaVersion': 1},
        'fiscal': {'configured': False, 'online': False, 'state': 'unknown'},
        'marta': {'configured': False, 'online': False, 'state': 'unknown'},
        'printer': {'configured': False, 'online': False, 'state': 'unknown'},
        'alerts': [{'code': 'LOCAL_AGENT_OFFLINE', 'severity': 'error', 'message': 'Local agent is offline.'}],
    }


class LocalAgentPOSSystemStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    command_service_class = LocalAgentCommandService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
        try:
            result = self.command_service_class().execute(
                restaurant=restaurant, command_type='system.status', payload={}, timeout_seconds=8
            )
        except LocalAgentUnavailableError:
            result = _offline_status(agent)
        except LocalAgentCommandError as error:
            return Response(
                {'detail': str(error), 'code': error.code, 'result': error.result},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'ok': True, 'status': result})
