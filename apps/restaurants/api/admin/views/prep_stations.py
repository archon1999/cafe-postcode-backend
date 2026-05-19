from rest_framework import generics

from apps.restaurants.api.admin.serializers import PrepStationSerializer
from apps.restaurants.helpers import get_prep_station_model
from apps.restaurants.selectors.resources import PrepStationListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant

PrepStation = get_prep_station_model()


class PrepStationListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = PrepStationSerializer

    def get_queryset(self):
        queryset = filter_queryset_by_optional_restaurant(
            PrepStation.objects.select_related('printer_integration').prefetch_related('cooks'),
            self.request,
        )
        return PrepStationListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class PrepStationDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PrepStationSerializer

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            PrepStation.objects.select_related('printer_integration').prefetch_related('cooks'),
            self.request,
        )

__all__ = ['PrepStationDetailView', 'PrepStationListCreateView']
