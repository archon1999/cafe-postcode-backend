from rest_framework import generics

from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.models import TableSession
from apps.floor.selectors.floor import TableSessionListFilters
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class TableSessionListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = TableSessionSerializer

    def get_queryset(self):
        queryset = (
            TableSession.objects.all()
            .select_related('hall', 'table', 'opened_by', 'assigned_waiter', 'merged_into')
        )
        queryset = filter_queryset_by_optional_restaurant(queryset, self.request)
        return TableSessionListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class TableSessionDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TableSessionSerializer

    def get_queryset(self):
        return (
            filter_queryset_by_optional_restaurant(TableSession.objects.all(), self.request)
            .select_related('hall', 'table', 'opened_by', 'assigned_waiter', 'merged_into')
        )

__all__ = ['TableSessionDetailView', 'TableSessionListCreateView']
