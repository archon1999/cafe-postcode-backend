from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.admin_serializers import LocalAgentFleetSerializer
from apps.local_agents.models import LocalAgent
from apps.local_agents.sanitization import sanitize_remote_logs_result, sanitize_remote_text
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from common.api.permissions import IsAdmin


SUPERUSER_PERMISSIONS = [permissions.IsAuthenticated, IsAdmin]
LOCAL_AGENT_ONLINE_MAX_AGE_SECONDS = 75
ORDERING_FIELDS = {
    'restaurantName': 'restaurant__name',
    'name': 'name',
    'status': 'status',
    'version': 'version',
    'lastSeenAt': 'last_seen_at',
}
REMOTE_ACTIONS = {
    'update': ('agent.update_now', 'auto_update', 8),
    'refresh_context': ('agent.refresh_context', 'context_refresh', 30),
    'restart': ('agent.restart', 'remote_restart', 8),
}


class LocalAgentFleetListView(generics.ListAPIView):
    permission_classes = SUPERUSER_PERMISSIONS
    serializer_class = LocalAgentFleetSerializer

    def get_queryset(self):
        queryset = LocalAgent.objects.select_related('restaurant').all()
        search = str(self.request.query_params.get('search') or '').strip()
        status_filter = str(self.request.query_params.get('status') or '').strip().lower()
        ordering = str(self.request.query_params.get('ordering') or '').strip()

        if search:
            queryset = queryset.filter(
                Q(restaurant__name__icontains=search)
                | Q(name__icontains=search)
                | Q(version__icontains=search)
            )

        online_cutoff = timezone.now() - timedelta(seconds=LOCAL_AGENT_ONLINE_MAX_AGE_SECONDS)
        online_query = Q(status=LocalAgent.Status.ONLINE, last_seen_at__gte=online_cutoff, is_active=True)
        if status_filter == LocalAgent.Status.ONLINE:
            queryset = queryset.filter(online_query)
        elif status_filter == LocalAgent.Status.OFFLINE:
            queryset = queryset.exclude(online_query)

        descending = ordering.startswith('-')
        ordering_key = ordering[1:] if descending else ordering
        ordering_field = ORDERING_FIELDS.get(ordering_key, 'restaurant__name')
        if descending:
            ordering_field = f'-{ordering_field}'
        return queryset.order_by(ordering_field, 'restaurant__name')


class LocalAgentFleetActionView(APIView):
    permission_classes = SUPERUSER_PERMISSIONS
    command_service_class = LocalAgentCommandService

    @staticmethod
    def get_agent(pk):
        return get_object_or_404(LocalAgent.objects.select_related('restaurant'), pk=pk, is_active=True)

    @staticmethod
    def command_error_response(error):
        if isinstance(error, LocalAgentUnavailableError):
            return Response({'detail': str(error), 'code': error.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {'detail': str(error), 'code': error.code, 'result': error.result},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class LocalAgentFleetDiagnosticsView(LocalAgentFleetActionView):
    def get(self, request, pk):
        agent = self.get_agent(pk)
        try:
            result = self.command_service_class().execute(
                restaurant=agent.restaurant,
                command_type='system.status',
                payload={},
                timeout_seconds=12,
            )
        except (LocalAgentUnavailableError, LocalAgentCommandError) as error:
            return self.command_error_response(error)
        return Response({'ok': True, 'agent': LocalAgentFleetSerializer(agent).data, 'status': result})


class LocalAgentFleetUpdateView(LocalAgentFleetActionView):
    def post(self, request, pk):
        agent = self.get_agent(pk)
        if not agent.is_online():
            return Response(
                {'detail': 'Local agent is offline.', 'code': 'LOCAL_AGENT_OFFLINE'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if 'auto_update' not in (agent.capabilities or []):
            return Response(
                {'detail': 'Installed Local Agent does not support remote updates.', 'code': 'AUTO_UPDATE_UNSUPPORTED'},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            result = self.command_service_class().execute(
                restaurant=agent.restaurant,
                command_type='agent.update_now',
                payload={},
                timeout_seconds=8,
            )
        except (LocalAgentUnavailableError, LocalAgentCommandError) as error:
            return self.command_error_response(error)
        return Response({'ok': True, 'result': result})


class LocalAgentFleetLogsView(LocalAgentFleetActionView):
    def get(self, request, pk):
        agent = self.get_agent(pk)
        if 'remote_logs' not in (agent.capabilities or []):
            return Response(
                {'detail': 'Installed Local Agent does not support remote logs.', 'code': 'REMOTE_LOGS_UNSUPPORTED'},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            result = self.command_service_class().execute(
                restaurant=agent.restaurant,
                command_type='agent.logs',
                payload={},
                timeout_seconds=8,
            )
        except (LocalAgentUnavailableError, LocalAgentCommandError) as error:
            return self.command_error_response(error)
        return Response({'ok': True, **sanitize_remote_logs_result(result)})


class LocalAgentFleetBulkActionView(LocalAgentFleetActionView):
    max_agents = 50

    def post(self, request):
        action = str(request.data.get('action') or '').strip()
        raw_ids = request.data.get('agent_ids', request.data.get('agentIds'))
        if action not in REMOTE_ACTIONS:
            return Response({'action': ['Unsupported action.']}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response({'agentIds': ['Select at least one Local Agent.']}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw_ids) > self.max_agents:
            return Response(
                {'agentIds': [f'At most {self.max_agents} Local Agents can be managed at once.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            agent_ids = list(dict.fromkeys(str(UUID(str(value))) for value in raw_ids))
        except (TypeError, ValueError, AttributeError):
            return Response({'agentIds': ['One or more Local Agent IDs are invalid.']}, status=status.HTTP_400_BAD_REQUEST)

        agents = {
            str(agent.id): agent
            for agent in LocalAgent.objects.select_related('restaurant').filter(pk__in=agent_ids, is_active=True)
        }
        command_type, capability, timeout_seconds = REMOTE_ACTIONS[action]

        def execute(agent_id):
            agent = agents.get(agent_id)
            if agent is None:
                return {'agentId': agent_id, 'ok': False, 'detail': 'Local Agent was not found.'}
            base = {'agentId': agent_id, 'restaurantName': agent.restaurant.name}
            if not agent.is_online():
                return {**base, 'ok': False, 'detail': 'Local Agent is offline.'}
            if capability not in (agent.capabilities or []):
                return {**base, 'ok': False, 'detail': f'Capability {capability} is not supported.'}
            try:
                result = self.command_service_class().execute(
                    restaurant=agent.restaurant,
                    command_type=command_type,
                    payload={},
                    timeout_seconds=timeout_seconds,
                )
            except (LocalAgentUnavailableError, LocalAgentCommandError) as error:
                return {**base, 'ok': False, 'detail': sanitize_remote_text(error)}
            return {**base, 'ok': True, 'result': result}

        with ThreadPoolExecutor(max_workers=min(8, len(agent_ids))) as executor:
            results = list(executor.map(execute, agent_ids))
        succeeded = sum(1 for item in results if item['ok'])
        return Response(
            {
                'ok': succeeded == len(results),
                'action': action,
                'succeeded': succeeded,
                'failed': len(results) - succeeded,
                'results': results,
            }
        )
