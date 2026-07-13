from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgent, LocalAgentEnrollmentToken
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.releases import agent_update_status
from apps.local_agents.serializers import LocalAgentEnrollmentSerializer, LocalAgentStatusSerializer
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.throttling import AgentEnrollmentRateThrottle


class LocalAgentEnrollmentTokenView(AdminPermissionRequiredMixin, APIView):
    def post(self, request):
        restaurant = get_request_restaurant(request)
        if not restaurant.is_active:
            return Response(
                {'restaurantId': ['Local Agent cannot be installed for an inactive restaurant.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        token, raw_token = LocalAgentEnrollmentToken.issue(restaurant=restaurant, issued_by=request.user)
        return Response(
            {
                'enrollmentToken': raw_token,
                'expiresAt': token.expires_at,
                'restaurantId': str(restaurant.id),
            },
            status=status.HTTP_201_CREATED,
        )


class LocalAgentEnrollView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AgentEnrollmentRateThrottle]

    @transaction.atomic
    def post(self, request):
        serializer = LocalAgentEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = serializer.validated_data['restaurant']
        agent, token = LocalAgent.issue_for_restaurant(
            restaurant=restaurant,
            name=serializer.validated_data.get('name', ''),
            version=serializer.validated_data.get('version', ''),
        )
        ws_url = request.build_absolute_uri('/ws/local-agent/')
        ws_url = ws_url.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        return Response(
            {
                'agentToken': token,
                'wsUrl': ws_url,
                'agent': LocalAgentStatusSerializer(agent).data,
            },
            status=status.HTTP_200_OK,
        )


class LocalAgentEnrollmentPreflightView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AgentEnrollmentRateThrottle]

    def post(self, request):
        serializer = LocalAgentEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restaurant = serializer.validated_data['restaurant']
        return Response(
            {
                'ok': True,
                'restaurantId': str(restaurant.id),
                'restaurantName': restaurant.name,
            }
        )


class LocalAgentTokenAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=401)
        return Response({'agent': LocalAgentStatusSerializer(agent).data})


class LocalAgentAdminStatusView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.select_related('restaurant').filter(restaurant=restaurant).first()
        if agent is None:
            return Response({'agent': None, 'update': None})
        agent_data = LocalAgentStatusSerializer(agent).data
        agent_data['online'] = agent.is_online()
        return Response({'agent': agent_data, 'update': agent_update_status(agent)})


class LocalAgentDiagnosticsView(AdminPermissionRequiredMixin, APIView):
    command_service_class = LocalAgentCommandService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        try:
            result = self.command_service_class().execute(
                restaurant=restaurant,
                command_type='system.status',
                payload={},
                timeout_seconds=12,
            )
        except LocalAgentUnavailableError as error:
            return Response({'detail': str(error), 'code': error.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LocalAgentCommandError as error:
            return Response(
                {'detail': str(error), 'code': error.code, 'result': error.result},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'ok': True, 'status': result})


class LocalAgentUpdateNowView(AdminPermissionRequiredMixin, APIView):
    command_service_class = LocalAgentCommandService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.filter(restaurant=restaurant, is_active=True).first()
        if agent is None or not agent.is_online():
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
                restaurant=restaurant,
                command_type='agent.update_now',
                payload={},
                timeout_seconds=8,
            )
        except LocalAgentUnavailableError as error:
            return Response({'detail': str(error), 'code': error.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LocalAgentCommandError as error:
            return Response(
                {'detail': str(error), 'code': error.code, 'result': error.result},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'ok': True, 'result': result})


class LocalAgentPrinterCheckView(AdminPermissionRequiredMixin, APIView):
    command_service_class = LocalAgentCommandService

    def post(self, request):
        restaurant = get_request_restaurant(request)
        payload = {
            'connectionType': request.data.get('connectionType') or request.data.get('connection_type') or '',
            'printerName': request.data.get('printerName') or request.data.get('printer_name') or '',
            'host': request.data.get('host') or '',
            'port': request.data.get('port') or None,
        }
        try:
            result = self.command_service_class().execute(
                restaurant=restaurant,
                command_type='printer.check',
                payload=payload,
                timeout_seconds=10,
            )
        except LocalAgentUnavailableError as error:
            return Response({'ok': False, 'error': str(error), 'code': error.code}, status=502)
        except LocalAgentCommandError as error:
            return Response({'ok': False, 'error': str(error), 'code': error.code, 'result': error.result}, status=502)
        return Response(result)
