from rest_framework import generics

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.serializers import (
    AdminOrderItemNoteSerializer,
    AdminOrderItemSerializer,
    AdminOrderSerializer,
    AdminPaymentSerializer,
    AdminReceiptSerializer,
)
from apps.admin.support import (
    AdminOrderItemNotesQuerysetMixin,
    AdminOrderItemsQuerysetMixin,
    AdminOrdersQuerysetMixin,
    AdminPaymentsQuerysetMixin,
    AdminReceiptsQuerysetMixin,
    OrderItemListFilters,
    OrderItemNoteListFilters,
    OrderListFilters,
    PaymentListFilters,
    ReceiptListFilters,
)


class OrderListView(AdminPermissionRequiredMixin, AdminOrdersQuerysetMixin, generics.ListAPIView):
    serializer_class = AdminOrderSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return OrderListFilters.from_request(self.request).apply(self.get_order_queryset())


class OrderDetailView(AdminPermissionRequiredMixin, AdminOrdersQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return self.get_order_queryset()


class OrderItemListView(AdminPermissionRequiredMixin, AdminOrderItemsQuerysetMixin, generics.ListAPIView):
    serializer_class = AdminOrderItemSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return OrderItemListFilters.from_request(self.request).apply(self.get_order_item_queryset())


class OrderItemDetailView(AdminPermissionRequiredMixin, AdminOrderItemsQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderItemSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return self.get_order_item_queryset()


class OrderItemNoteListView(AdminPermissionRequiredMixin, AdminOrderItemNotesQuerysetMixin, generics.ListAPIView):
    serializer_class = AdminOrderItemNoteSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return OrderItemNoteListFilters.from_request(self.request).apply(self.get_order_item_note_queryset())


class OrderItemNoteDetailView(AdminPermissionRequiredMixin, AdminOrderItemNotesQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderItemNoteSerializer
    permission_code = 'orders.view'

    def get_queryset(self):
        return self.get_order_item_note_queryset()


class PaymentListView(AdminPermissionRequiredMixin, AdminPaymentsQuerysetMixin, generics.ListAPIView):
    serializer_class = AdminPaymentSerializer
    permission_code = 'payments.view'

    def get_queryset(self):
        return PaymentListFilters.from_request(self.request).apply(self.get_payment_queryset())


class PaymentDetailView(AdminPermissionRequiredMixin, AdminPaymentsQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = AdminPaymentSerializer
    permission_code = 'payments.view'

    def get_queryset(self):
        return self.get_payment_queryset()


class ReceiptListView(AdminPermissionRequiredMixin, AdminReceiptsQuerysetMixin, generics.ListAPIView):
    serializer_class = AdminReceiptSerializer
    permission_code = 'payments.view'

    def get_queryset(self):
        return ReceiptListFilters.from_request(self.request).apply(self.get_receipt_queryset())


class ReceiptDetailView(AdminPermissionRequiredMixin, AdminReceiptsQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = AdminReceiptSerializer
    permission_code = 'payments.view'

    def get_queryset(self):
        return self.get_receipt_queryset()
