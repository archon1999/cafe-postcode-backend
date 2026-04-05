from rest_framework import generics

from apps.restaurants.api.admin.serializers import DistributionPointSerializer
from apps.restaurants.helpers import get_distribution_point_model
from apps.restaurants.selectors.resources import DistributionPointListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant

DistributionPoint = get_distribution_point_model()


class DistributionPointListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DistributionPointSerializer

    def get_queryset(self):
        queryset = filter_queryset_by_optional_restaurant(DistributionPoint.objects.all(), self.request)
        return DistributionPointListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class DistributionPointDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DistributionPointSerializer

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(DistributionPoint.objects.all(), self.request)

__all__ = ['DistributionPointDetailView', 'DistributionPointListCreateView']
