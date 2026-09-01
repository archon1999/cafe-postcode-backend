import json

from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_payment_model
from apps.billing.models import CashShift
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


def _kitchen_print_document_ids(order, *, exclude=None):
    excluded_ids = {str(document_id) for document_id in (exclude or [])}
    return [
        str(document_id)
        for document_id in order.kitchen_tickets.filter(
            routed_via__in=['printer', 'both'],
            print_document__isnull=False,
        ).values_list('print_document_id', flat=True)
        if str(document_id) not in excluded_ids
    ]


def _payment_request_payload(request):
    payload = request.data.copy()
    if 'finalTotal' in payload and 'final_total' not in payload:
        payload['final_total'] = payload.pop('finalTotal')
    if 'totalOverrideReason' in payload and 'total_override_reason' not in payload:
        payload['total_override_reason'] = payload.pop('totalOverrideReason')
    header_operation_id = str(request.headers.get('X-Edge-Operation-ID') or '').strip()
    if not header_operation_id:
        return payload
    body_operation_ids = {
        str(payload.get(key) or '').strip()
        for key in ('edge_operation_id', 'edgeOperationId')
        if str(payload.get(key) or '').strip()
    }
    if any(operation_id != header_operation_id for operation_id in body_operation_ids):
        raise ValidationError({'edgeOperationId': _('Header and body operation IDs must match.')})
    payload['edge_operation_id'] = header_operation_id
    payload.pop('edgeOperationId', None)
    return payload


class PaymentCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_payment_service_class = OrderPaymentService
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        payment_payload = _payment_request_payload(request)
        trusted_edge_replay = bool(
            getattr(request._request, 'trusted_edge_replay', False)
        )
        edge_cash_shift_id = payment_payload.pop(
            'edgeCashShiftId', payment_payload.pop('edge_cash_shift_id', None)
        )
        if edge_cash_shift_id and not trusted_edge_replay:
            raise ValidationError(
                {'edgeCashShiftId': _('Only a trusted local agent may bind a payment to a shift.')}
            )
        order = generics.get_object_or_404(
            Order.objects.select_related('restaurant', 'table_session__table'),
            pk=pk,
            restaurant=restaurant,
        )
        existing_kitchen_documents = _kitchen_print_document_ids(order)
        if edge_cash_shift_id:
            cash_shift = CashShift.objects.filter(
                pk=edge_cash_shift_id,
                cash_desk__restaurant=restaurant,
            ).first()
            if cash_shift is None:
                raise ValidationError(
                    {
                        'code': 'EDGE_CASH_SHIFT_NOT_FOUND',
                        'edgeCashShiftId': _('The originating cashier shift was not found.'),
                    }
                )
        else:
            cash_shift = self.shift_service_class().get_active_shift(
                restaurant=restaurant, user=request.user
            )
        result = self.order_payment_service_class().process(
            order=order,
            payload=payment_payload,
            received_by=request.user,
            cash_shift=cash_shift,
            trusted_edge_replay=trusted_edge_replay,
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
                'kitchenPrintDocuments': _kitchen_print_document_ids(
                    result['order'],
                    exclude=existing_kitchen_documents,
                ),
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
            final_total=request.data.get('final_total', request.data.get('finalTotal')),
            total_override_reason=request.data.get(
                'total_override_reason', request.data.get('totalOverrideReason', '')
            ),
            service_fee_quote=request.data.get('service_fee_quote', request.data.get('serviceFeeQuote')),
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
        existing_kitchen_documents = _kitchen_print_document_ids(payment.order)
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
                'kitchenPrintDocuments': _kitchen_print_document_ids(
                    result['order'],
                    exclude=existing_kitchen_documents,
                ),
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
        trusted_edge_replay = bool(getattr(request._request, 'trusted_edge_replay', False))
        edge_fiscal_results = request.data.get('edge_fiscal_results')
        edge_fiscal_results_json = request.data.get('edge_fiscal_results_json')
        if (edge_fiscal_results is not None or edge_fiscal_results_json is not None) and not trusted_edge_replay:
            raise ValidationError({'edgeFiscalResults': 'Only a trusted local agent may submit fiscal results.'})
        if edge_fiscal_results_json is not None:
            if edge_fiscal_results is not None:
                raise ValidationError({'edgeFiscalResults': 'Submit fiscal results in only one format.'})
            try:
                edge_fiscal_results = json.loads(edge_fiscal_results_json)
            except (TypeError, ValueError) as error:
                raise ValidationError({'edgeFiscalResults': 'Fiscal results JSON is invalid.'}) from error
        validated_edge_fiscal_results = None
        if edge_fiscal_results is not None:
            validated_edge_fiscal_results = OrderPaymentService._validated_edge_fiscal_results(
                results=edge_fiscal_results,
                cash_desk=payment.cash_desk,
                register_fiscal=True,
                expected_amount=int(payment.order.total or 0),
            )
        result = self.service_class().retry(payment=payment, fiscal_results=validated_edge_fiscal_results)
        retry_results = result.get('results') or []
        result_items = [item for item in retry_results if isinstance(item, dict)]
        successful = bool(result_items) and all(item.get('ok') for item in result_items)
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


class PaymentPrintDocumentView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService
    refund_service_class = PaymentRefundService
    feature_gate_service_class = FeatureGateService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        payment = generics.get_object_or_404(
            Payment.objects.select_related('order'),
            pk=pk,
            order__restaurant=restaurant,
        )
        shift = self.shift_service_class().get_active_shift(restaurant=restaurant, user=request.user)
        receipt = self.refund_service_class().ensure_payment_print_document(
            payment=payment,
            created_by=request.user,
            cash_shift=shift,
        )
        return Response({'receipt': ReceiptSerializer(receipt).data})


__all__ = [
    'MartaCardPaymentInitiateView',
    'MartaTerminalResultView',
    'PaymentCreateView',
    'PaymentFiscalRetryView',
    'PaymentPrintDocumentView',
    'PaymentRefundView',
]
