from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order, Payment
from apps.orders.serializers import OrderSerializer, PaymentSerializer, ReceiptSerializer
from apps.orders.services import CashShiftService, OrderPaymentService
from apps.organizations.services import FeatureGateService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class PaymentCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'payments.manage'
    order_payment_service_class = OrderPaymentService
    shift_service_class = CashShiftService
    feature_gate_service_class = FeatureGateService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        order = generics.get_object_or_404(
            Order.objects.select_related('table_session__table'),
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
            return Response({'payment': PaymentSerializer(payment).data}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'order': OrderSerializer(result['order']).data,
                'payment': PaymentSerializer(payment).data,
                'receipt': ReceiptSerializer(result['receipt']).data if result['receipt'] else None,
            },
            status=status.HTTP_201_CREATED,
        )
