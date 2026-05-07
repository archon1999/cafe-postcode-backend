from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_receipt_model
from apps.billing.serializers import ReceiptSerializer
from apps.billing.services import CashShiftService, OrderPrebillService, PaymentRefundService
from apps.platform.services import FeatureGateService
from apps.sales.helpers import get_order_model
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant

Receipt = get_receipt_model()
Order = get_order_model()


class OrderPrebillPrintView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = OrderPrebillService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.select_related(
                'restaurant',
                'table_session',
                'table_session__table',
                'opened_by',
            ).prefetch_related('items__catalog_item'),
            pk=pk,
            restaurant=restaurant,
        )
        required_permission = (
            POS_TABLES_MANAGE_PERMISSION
            if order.table_session_id
            else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        )
        require_any_permission_code(request.user, required_permission)
        outcome = self.service_class().print(order=order)
        return Response(
            {
                'receipt': ReceiptSerializer(outcome['receipt']).data,
                'result': outcome['result'],
            }
        )


class ReceiptPrintResultView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    service_class = OrderPrebillService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        receipt = generics.get_object_or_404(
            Receipt.objects.select_related('order'),
            pk=pk,
            order__restaurant=restaurant,
        )
        required_permission = (
            POS_TABLES_MANAGE_PERMISSION
            if receipt.order.table_session_id
            else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        )
        require_any_permission_code(request.user, required_permission)

        result = request.data.get('result', request.data)
        if not isinstance(result, dict):
            raise ValidationError({'detail': 'Print result must be an object.'})

        updated_receipt = self.service_class().record_print_result(receipt=receipt, result=result)
        return Response(
            {
                'receipt': ReceiptSerializer(updated_receipt).data,
                'result': (updated_receipt.payload or {}).get('result', {}),
            }
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

__all__ = [
    'OrderPrebillPrintView',
    'ReceiptPrintResultView',
    'ReceiptReprintView',
]
