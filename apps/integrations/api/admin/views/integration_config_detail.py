from rest_framework import generics, permissions

from apps.integrations.models import IntegrationConfig
from apps.integrations.api.admin.serializers import IntegrationConfigSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class IntegrationConfigDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = IntegrationConfigSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return IntegrationConfig.objects.filter(restaurant=restaurant)
