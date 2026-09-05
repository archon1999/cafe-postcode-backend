from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api.admin.serializers import AdminPaymentSerializer, AdminReceiptSerializer
from apps.billing.selectors.payments import PaymentListFilters, admin_payment_queryset
from apps.billing.services import PaymentFiscalRetryService
from apps.billing.services.financial_authority import dispatch_to_financial_owner
from apps.billing.api.pos.views.financial_commands import FinancialCommandStatusView
from common.api.admin_permissions import AdminPermissionRequiredMixin


class PaymentListView(AdminPermissionRequiredMixin, generics.ListAPIView):
    serializer_class = AdminPaymentSerializer

    def get_queryset(self):
        return PaymentListFilters.from_request(self.request).apply(admin_payment_queryset(self.request))


class PaymentDetailView(AdminPermissionRequiredMixin, generics.RetrieveAPIView):
    serializer_class = AdminPaymentSerializer

    def get_queryset(self):
        return admin_payment_queryset(self.request)


class PaymentFiscalRetryView(AdminPermissionRequiredMixin, APIView):
    service_class = PaymentFiscalRetryService

    def post(self, request, pk):
        payment = generics.get_object_or_404(admin_payment_queryset(request), pk=pk)
        # Keep execution with the original POS cashier; an admin-only account
        # has no offline PIN/session. The durable command separately records
        # the authenticated admin actor for audit and result recovery.
        cashier = payment.received_by
        if cashier is None or not cashier.is_active or not cashier.can_access_pos_ui:
            return Response({
                'code': 'FINANCIAL_RETRY_CASHIER_UNAVAILABLE',
                'detail': 'The original POS cashier must be available on the assigned Agent before recovery.',
            }, status=status.HTTP_409_CONFLICT)
        return dispatch_to_financial_owner(request=request, restaurant=payment.order.restaurant,
            path=f'/api/v1/pos/billing/payments/{payment.pk}/retry-fiscal/', execution_user=cashier)


class AdminFinancialCommandStatusView(AdminPermissionRequiredMixin, FinancialCommandStatusView):
    """Admin auth surface and explicit restaurant scope; same durable journal."""


__all__ = ['PaymentDetailView', 'PaymentFiscalRetryView', 'PaymentListView']
