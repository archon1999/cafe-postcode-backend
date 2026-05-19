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
        queryset = IntegrationConfig.objects.filter(restaurant=restaurant)
        kind_in = self.request.query_params.get('kindIn') or self.request.query_params.get('kind_in')
        if kind_in:
            queryset = queryset.filter(kind__in=[item.strip() for item in kind_in.split(',') if item.strip()])
        is_enabled = self.request.query_params.get('isEnabled') or self.request.query_params.get('is_enabled')
        if is_enabled is not None:
            queryset = queryset.filter(is_enabled=str(is_enabled).lower() in {'1', 'true', 'yes'})
        search = str(self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(provider__icontains=search)
        return queryset.order_by('kind', 'provider')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
