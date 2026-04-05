from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.helpers import get_receipt_model
from apps.billing.serializers import ReceiptSerializer
from apps.billing.services import CashShiftService, PaymentRefundService
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant

Receipt = get_receipt_model()


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

__all__ = ['ReceiptReprintView']
