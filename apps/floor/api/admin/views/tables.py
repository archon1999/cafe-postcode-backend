from rest_framework import generics

from apps.floor.api.admin.serializers import DiningTableSerializer
from apps.floor.models import DiningTable
from apps.floor.selectors.floor import DiningTableListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class DiningTableListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = DiningTableSerializer

    def get_queryset(self):
        queryset = (
            DiningTable.objects.all()
            .select_related('hall', 'zone')
            .prefetch_related('table_sessions')
        )
        queryset = filter_queryset_by_optional_restaurant(queryset, self.request, lookup='hall__zone_or_cabin__restaurant')
        return DiningTableListFilters.from_request(self.request).apply(queryset)


class DiningTableDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DiningTableSerializer

    def get_queryset(self):
        return (
            filter_queryset_by_optional_restaurant(DiningTable.objects.all(), self.request, lookup='hall__zone_or_cabin__restaurant')
            .select_related('hall', 'zone')
            .prefetch_related('table_sessions')
        )

__all__ = ['DiningTableDetailView', 'DiningTableListCreateView']
