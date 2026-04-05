from rest_framework import generics

from apps.restaurants.api.admin.serializers import DeviceSerializer
from apps.restaurants.helpers import get_device_model
from apps.restaurants.selectors.resources import DeviceListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant

Device = get_device_model()


class DeviceListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DeviceSerializer

    def get_queryset(self):
        queryset = filter_queryset_by_optional_restaurant(
            Device.objects.select_related('primary_hall').prefetch_related('allowed_halls'),
            self.request,
        )
        return DeviceListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class DeviceDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DeviceSerializer

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            Device.objects.select_related('primary_hall').prefetch_related('allowed_halls'),
            self.request,
        )

__all__ = ['DeviceDetailView', 'DeviceListCreateView']
