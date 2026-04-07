from rest_framework import generics, permissions

from apps.integrations.models import IntegrationConfig
from apps.integrations.api.admin.serializers import IntegrationConfigSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class IntegrationConfigListCreateView(generics.ListCreateAPIView):
    serializer_class = IntegrationConfigSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return IntegrationConfig.objects.filter(restaurant=restaurant).order_by('kind', 'provider')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
