from rest_framework import generics, permissions

from apps.integrations.models import IntegrationConfig
from apps.integrations.serializers import IntegrationConfigSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch, get_request_restaurant


class IntegrationConfigListCreateView(generics.ListCreateAPIView):
    serializer_class = IntegrationConfigSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'integrations.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return IntegrationConfig.objects.filter(restaurant=restaurant).order_by('kind', 'provider')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant, branch=get_request_branch(self.request, restaurant))
