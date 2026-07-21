import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.services import LocalAgentCommandService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

logger = logging.getLogger(__name__)
STATUS_REFRESH_INTERVAL = timedelta(minutes=1)


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


def _pending_status(agent):
    return {
        'agent': {
            'online': True,
            'version': agent.version,
            'restaurantId': str(agent.restaurant_id),
        },
        'backend': {'online': True, 'offlineMode': False},
        'sync': {'ready': False, 'pendingOutbox': 0, 'failedOutbox': 0, 'schemaVersion': 1},
        'fiscal': {'configured': False, 'online': False, 'state': 'unknown'},
        'marta': {'configured': False, 'online': False, 'state': 'unknown'},
        'printer': {'configured': False, 'online': False, 'state': 'unknown'},
        'alerts': [],
    }


def _cached_status(agent):
    command = (
        LocalAgentCommand.objects.filter(
            agent=agent,
            command_type='system.status',
            status=LocalAgentCommand.Status.SUCCEEDED,
        )
        .only('result')
        .first()
    )
    cached_result = command.result if command and isinstance(command.result, dict) else None
    result = dict(cached_result) if cached_result else _pending_status(agent)
    cached_agent = result.get('agent') if isinstance(result.get('agent'), dict) else {}
    result['agent'] = {
        **cached_agent,
        'online': True,
        'version': agent.version,
        'restaurantId': str(agent.restaurant_id),
    }
    return result


def _request_status_refresh(command_service, *, restaurant, agent):
    threshold = timezone.now() - STATUS_REFRESH_INTERVAL
    recently_requested = LocalAgentCommand.objects.filter(
        agent=agent,
        command_type='system.status',
        created_at__gte=threshold,
    ).exists()
    if recently_requested:
        return
    try:
        command_service.enqueue(
            restaurant=restaurant,
            command_type='system.status',
            payload={},
            timeout_seconds=8,
        )
    except Exception as error:  # noqa: BLE001 - health refresh is best-effort and must never block POS.
        logger.warning('Local Agent status refresh could not be queued: %s', error)


class LocalAgentPOSSystemStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    command_service_class = LocalAgentCommandService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
        if agent is None or not agent.is_online():
            return Response({'ok': True, 'status': _offline_status(agent)})

        result = _cached_status(agent)
        _request_status_refresh(self.command_service_class(), restaurant=restaurant, agent=agent)
        return Response({'ok': True, 'status': result})
