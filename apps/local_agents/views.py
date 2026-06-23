from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgent
from apps.local_agents.serializers import LocalAgentRestaurantCodeSerializer, LocalAgentStatusSerializer
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant


class LocalAgentRestaurantCodeAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LocalAgentRestaurantCodeSerializer(data=request.data)
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
            }
        )


class LocalAgentTokenAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        token = str(request.headers.get('Authorization', '')).removeprefix('Bearer ').strip()
        if not token:
            token = str(request.query_params.get('token', '')).strip()
        agent = LocalAgent.authenticate_token(token) if token else None
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=401)
        return Response({'agent': LocalAgentStatusSerializer(agent).data})


class LocalAgentAdminStatusView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.select_related('restaurant').filter(restaurant=restaurant).first()
        return Response({'agent': LocalAgentStatusSerializer(agent).data if agent else None})


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
