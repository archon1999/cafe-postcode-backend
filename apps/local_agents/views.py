from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.models import LocalAgent
from apps.local_agents.serializers import LocalAgentRestaurantCodeSerializer, LocalAgentStatusSerializer
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


class LocalAgentAdminStatusView(AdminPermissionRequiredMixin, APIView):
    def get(self, request):
        restaurant = get_request_restaurant(request)
        agent = LocalAgent.objects.select_related('restaurant').filter(restaurant=restaurant).first()
        return Response({'agent': LocalAgentStatusSerializer(agent).data if agent else None})
