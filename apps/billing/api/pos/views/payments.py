from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_payment_model
from apps.billing.serializers import (
    MartaTerminalResultSerializer,
    PaymentRefundCreateSerializer,
    PaymentRefundSerializer,
    PaymentSerializer,
    ReceiptSerializer,
)
from apps.billing.services import CashShiftService, OrderPaymentService, PaymentFiscalRetryService, PaymentRefundService
from apps.platform.services import FeatureGateService
from apps.sales.helpers import get_order_model
from apps.sales.serializers import OrderSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

Order = get_order_model()
Payment = get_payment_model()


class PaymentCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_payment_service_class = OrderPaymentService
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        order = generics.get_object_or_404(
            Order.objects.select_related('restaurant', 'table_session__table'),
            pk=pk,
            restaurant=restaurant,
        )
        cash_shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        result = self.order_payment_service_class().process(
            order=order,
            payload=request.data,
            received_by=request.user,
            cash_shift=cash_shift,
        )
        payment = result['payment']
        if payment.status == Payment.Status.FAILED:
            return Response(
                {
                    'detail': result.get('detail') or 'Payment charge failed.',
                    'payment': PaymentSerializer(payment).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                'order': OrderSerializer(result['order']).data,
                'payment': PaymentSerializer(payment).data,
                'receipt': ReceiptSerializer(result['receipt']).data if result['receipt'] else None,
                'receipts': ReceiptSerializer(result.get('receipts') or [], many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MartaCardPaymentInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_payment_service_class = OrderPaymentService
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        order = generics.get_object_or_404(
            Order.objects.select_related('restaurant', 'table_session__table'),
            pk=pk,
            restaurant=restaurant,
        )
        cash_shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        result = self.order_payment_service_class().initiate_marta_card_payment(
            order=order,
            amount=request.data.get('amount'),
            register_fiscal=bool(request.data.get('register_fiscal', True)),
            received_by=request.user,
            cash_shift=cash_shift,
        )
        return Response(
            {
                'payment': PaymentSerializer(result['payment']).data,
                'marta': result['marta'],
            },
            status=status.HTTP_201_CREATED,
        )


class MartaTerminalResultView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = OrderPaymentService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        serializer = MartaTerminalResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        terminal_result = dict(request.data)
        payment = generics.get_object_or_404(
            Payment.objects.select_related('order', 'order__restaurant', 'cash_desk', 'cash_shift'),
            pk=pk,
            order__restaurant=restaurant,
        )
        result = self.service_class().complete_marta_terminal_payment(
            payment=payment,
            terminal_result=terminal_result,
            received_by=request.user,
        )
        if result['payment'].status == Payment.Status.FAILED:
            return Response(
                {
                    'detail': result.get('detail') or 'Payment charge failed.',
                    'payment': PaymentSerializer(result['payment']).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                'order': OrderSerializer(result['order']).data,
                'payment': PaymentSerializer(result['payment']).data,
                'receipt': ReceiptSerializer(result['receipt']).data if result['receipt'] else None,
                'receipts': ReceiptSerializer(result.get('receipts') or [], many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


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


class PaymentFiscalRetryView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = PaymentFiscalRetryService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        payment = generics.get_object_or_404(
            Payment.objects.select_related('order', 'cash_desk'),
            pk=pk,
            order__restaurant=restaurant,
        )
        result = self.service_class().retry(payment=payment)
        retry_results = result.get('results') or []
        successful = any(item.get('ok') for item in retry_results if isinstance(item, dict))
        response_status = status.HTTP_200_OK if successful else status.HTTP_400_BAD_REQUEST
        failed_result = next((item for item in retry_results if isinstance(item, dict) and not item.get('ok')), {})
        return Response(
            {
                'detail': '' if successful else (failed_result.get('detail') or failed_result.get('message') or 'Fiscal retry failed.'),
                'payment': PaymentSerializer(result['payment']).data,
                'receipt': ReceiptSerializer(result['receipt']).data if result['receipt'] else None,
                'receipts': ReceiptSerializer(result.get('receipts') or [], many=True).data,
                'result': result['result'],
                'results': retry_results,
            },
            status=response_status,
        )


__all__ = [
    'MartaCardPaymentInitiateView',
    'MartaTerminalResultView',
    'PaymentCreateView',
    'PaymentFiscalRetryView',
    'PaymentRefundView',
]
