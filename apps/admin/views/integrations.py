from rest_framework import generics

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import IntegrationConfigSerializer
from apps.admin.support import integration_config_queryset
from common.api.scopes import get_request_restaurant


class IntegrationConfigListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = IntegrationConfigSerializer

    def get_queryset(self):
        return integration_config_queryset(self.request, include_ordering=True)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)


class IntegrationConfigDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = IntegrationConfigSerializer

    def get_queryset(self):
        return integration_config_queryset(self.request)
