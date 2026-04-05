from rest_framework import generics

from apps.billing.api.admin.serializers import AdminReceiptSerializer
from apps.billing.selectors.payments import ReceiptListFilters, admin_receipt_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class ReceiptListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminReceiptSerializer

    def get_queryset(self):
        return ReceiptListFilters.from_request(self.request).apply(admin_receipt_queryset(self.request))


class ReceiptDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminReceiptSerializer

    def get_queryset(self):
        return admin_receipt_queryset(self.request)

__all__ = ['ReceiptDetailView', 'ReceiptListView']
