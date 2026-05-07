from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.api.admin.serializers import AdminPaymentSerializer, AdminReceiptSerializer
from apps.billing.selectors.payments import PaymentListFilters, admin_payment_queryset
from apps.billing.services import PaymentFiscalRetryService
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
        outcome = self.service_class().retry(payment=payment)
        response_status = status.HTTP_200_OK if outcome['result'].get('ok') else status.HTTP_400_BAD_REQUEST
        return Response(
            {
                'payment': AdminPaymentSerializer(outcome['payment']).data,
                'receipt': AdminReceiptSerializer(outcome['receipt']).data,
                'result': outcome['result'],
            },
            status=response_status,
        )


__all__ = ['PaymentDetailView', 'PaymentFiscalRetryView', 'PaymentListView']
