from rest_framework import generics

from apps.sales.api.admin.serializers import AdminOrderItemNoteSerializer
from apps.sales.selectors.orders import OrderItemNoteListFilters, admin_order_item_note_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class OrderItemNoteListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminOrderItemNoteSerializer

    def get_queryset(self):
        return OrderItemNoteListFilters.from_request(self.request).apply(admin_order_item_note_queryset(self.request))


class OrderItemNoteDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderItemNoteSerializer

    def get_queryset(self):
        return admin_order_item_note_queryset(self.request)

__all__ = ['OrderItemNoteDetailView', 'OrderItemNoteListView']
