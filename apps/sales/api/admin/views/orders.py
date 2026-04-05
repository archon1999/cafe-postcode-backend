from rest_framework import generics

from apps.sales.api.admin.serializers import AdminOrderSerializer
from apps.sales.selectors.orders import OrderListFilters, admin_order_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class OrderListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminOrderSerializer

    def get_queryset(self):
        return OrderListFilters.from_request(self.request).apply(admin_order_queryset(self.request))


class OrderDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderSerializer

    def get_queryset(self):
        return admin_order_queryset(self.request)

__all__ = ['OrderDetailView', 'OrderListView']
