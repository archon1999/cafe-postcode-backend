from rest_framework import generics

from apps.billing.api.admin.serializers import AdminPaymentSerializer
from apps.billing.selectors.payments import PaymentListFilters, admin_payment_queryset
from common.api.admin_permissions import AdminPermissionRequiredMixin


class PaymentListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminPaymentSerializer

    def get_queryset(self):
        return PaymentListFilters.from_request(self.request).apply(admin_payment_queryset(self.request))


class PaymentDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminPaymentSerializer

    def get_queryset(self):
        return admin_payment_queryset(self.request)

__all__ = ['PaymentDetailView', 'PaymentListView']
