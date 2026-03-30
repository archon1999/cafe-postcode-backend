from rest_framework import generics, permissions

from apps.integrations.models import IntegrationConfig
from apps.integrations.serializers import IntegrationConfigSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class IntegrationConfigDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = IntegrationConfigSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'integrations.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return IntegrationConfig.objects.filter(restaurant=restaurant)
