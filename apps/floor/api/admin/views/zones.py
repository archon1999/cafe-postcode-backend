from rest_framework import generics

from apps.floor.api.admin.serializers import ZoneOrCabinSerializer
from apps.floor.models import ZoneOrCabin
from apps.floor.selectors.floor import ZoneListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class ZoneListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = ZoneOrCabinSerializer

    def get_queryset(self):
        queryset = filter_queryset_by_optional_restaurant(ZoneOrCabin.objects.all(), self.request)
        return ZoneListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class ZoneDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ZoneOrCabinSerializer

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(ZoneOrCabin.objects.all(), self.request)

__all__ = ['ZoneDetailView', 'ZoneListCreateView']
