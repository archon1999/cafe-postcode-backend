from rest_framework import generics

from apps.sales.api.admin.serializers import AdminOrderItemSerializer
from apps.sales.selectors.orders import OrderItemListFilters, admin_order_item_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class OrderItemListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminOrderItemSerializer

    def get_queryset(self):
        return OrderItemListFilters.from_request(self.request).apply(admin_order_item_queryset(self.request))


class OrderItemDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderItemSerializer

    def get_queryset(self):
        return admin_order_item_queryset(self.request)

__all__ = ['OrderItemDetailView', 'OrderItemListView']
