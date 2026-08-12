from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.services import CashShiftService
from apps.printing.services import create_order_precheck_print_document
from apps.sales.models import Order, OrderItem
from common.api.permissions import (
    EndpointRBACPermission,
    POS_PAYMENTS_CREATE_PERMISSION,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class OrderPrecheckPrintDocumentView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    shift_service_class = CashShiftService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.select_related(
                "restaurant",
                "table_session__table",
                "table_session__hall",
                "opened_by",
                "cashier",
            ).prefetch_related("items__catalog_item", "items__modifiers"),
            pk=pk,
            restaurant=restaurant,
        )
        require_any_permission_code(
            request.user,
            POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION,
            POS_PAYMENTS_CREATE_PERMISSION,
        )
        if order.status in {Order.Status.CLOSED, Order.Status.CANCELLED}:
            raise ValidationError({"detail": "Closed or cancelled orders cannot be printed as a precheck."})
        if not order.items.exclude(status=OrderItem.Status.CANCELLED).exists():
            raise ValidationError({"detail": "Order has no items."})

        cash_desk = self.shift_service_class().get_precheck_print_cash_desk(
            restaurant=restaurant,
            user=request.user,
        )
        document = create_order_precheck_print_document(
            order=order,
            cash_desk=cash_desk,
            created_by=request.user,
        )
        return Response({"printDocument": str(document.id)})
