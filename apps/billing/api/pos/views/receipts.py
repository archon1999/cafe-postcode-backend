from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_receipt_model
from apps.billing.serializers import ReceiptSerializer
from apps.billing.services import CashShiftService, OrderPrebillService, PaymentRefundService
from apps.integrations.services import print_receipt_text
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
    shift_service_class = CashShiftService

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
        cash_desk = self.shift_service_class().get_prebill_print_cash_desk(restaurant=restaurant, user=request.user)
        outcome = self.service_class().print(order=order, cash_desk=cash_desk)
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


class ReceiptRawPrintView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService

    @staticmethod
    def _payload_qr_code(payload):
        if not isinstance(payload, dict):
            return ''
        direct = payload.get('qr_code_url') or payload.get('qrCodeUrl')
        if direct:
            return str(direct).strip()
        response = payload.get('response')
        if isinstance(response, dict):
            return str(response.get('QRCodeURL') or '').strip()
        return ''

    def post(self, request, pk=None):
        restaurant = get_request_restaurant(request)
        receipt = None
        if pk is not None:
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
            payload = receipt.payload or {}
            job_name = f'Cafe Postcode Receipt {receipt.id}'
        else:
            require_any_permission_code(request.user, POS_TAKEAWAY_MENU_VIEW_PERMISSION)
            payload = request.data.get('payload') if isinstance(request.data, dict) else None
            if not isinstance(payload, dict):
                payload = {}
            job_name = 'Cafe Postcode Receipt'

        text = request.data.get('text') if isinstance(request.data, dict) else ''
        text = str(text or '').strip()
        if not text:
            raise ValidationError({'text': 'Receipt text is required.'})

        cash_desk = self.shift_service_class().get_prebill_print_cash_desk(restaurant=restaurant, user=request.user)
        qr_code = request.data.get('qr_code') if isinstance(request.data, dict) else ''
        qr_code = str(qr_code or '').strip() or self._payload_qr_code(payload)
        qr_raster_base64 = request.data.get('qr_raster_base64') if isinstance(request.data, dict) else ''
        result = print_receipt_text(
            restaurant=restaurant,
            text=text,
            qr_code=qr_code,
            qr_raster_base64=str(qr_raster_base64 or '').strip(),
            cash_desk=cash_desk,
            job_name=job_name,
        )
        if receipt is not None:
            receipt_payload = dict(receipt.payload or {})
            receipt_payload['raw_print_result'] = result
            receipt.payload = receipt_payload
            if result.get('ok'):
                receipt.status = Receipt.Status.SENT
            receipt.save(update_fields=['payload', 'status', 'updated_at'])
            receipt.refresh_from_db()

        return Response(
            {
                'receipt': ReceiptSerializer(receipt).data if receipt is not None else None,
                'result': result,
                'payload': payload,
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
    'ReceiptRawPrintView',
    'ReceiptReprintView',
]
