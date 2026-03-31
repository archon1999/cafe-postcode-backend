from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Payment, Receipt
from apps.orders.serializers import PaymentRefundSerializer, ReceiptSerializer
from apps.orders.serializers.cashier_context import PaymentRefundCreateSerializer
from apps.orders.services import CashShiftService, PaymentRefundService
from apps.organizations.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PaymentRefundView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    refund_service_class = PaymentRefundService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        serializer = PaymentRefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = generics.get_object_or_404(Payment.objects.select_related('order'), pk=pk, order__restaurant=restaurant)
        shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        result = self.refund_service_class().refund(
            payment=payment,
            refunded_by=request.user,
            cash_shift=shift,
            reason=serializer.validated_data.get('reason', ''),
        )
        return Response(
            {
                'refund': PaymentRefundSerializer(result['refund']).data,
                'receipt': ReceiptSerializer(result['receipt']).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ReceiptReprintView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    refund_service_class = PaymentRefundService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        receipt = generics.get_object_or_404(Receipt.objects.select_related('order'), pk=pk, order__restaurant=restaurant)
        shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        result = self.refund_service_class().reprint(receipt=receipt, cash_shift=shift)
        receipt.refresh_from_db()
        return Response({'receipt': ReceiptSerializer(receipt).data, 'result': result})
