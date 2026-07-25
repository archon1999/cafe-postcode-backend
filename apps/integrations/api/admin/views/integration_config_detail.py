from rest_framework import generics, permissions

from apps.integrations.models import IntegrationConfig
from apps.integrations.api.admin.serializers import IntegrationConfigSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class IntegrationConfigDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = IntegrationConfigSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            IntegrationConfig.objects.select_related("restaurant"),
            self.request,
        )
