from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.helpers import get_order_model
from apps.sales.serializers import OrderSerializer
from apps.sales.services.marking import OrderMarkingScanService, marking_status
from common.api.permissions import (
    EndpointRBACPermission,
    POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION,
    POS_PAYMENT_ORDER_ITEMS_DELETE_PERMISSION,
    POS_PAYMENTS_CREATE_PERMISSION,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant

Order = get_order_model()


class OrderScanMarkingView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    scan_service_class = OrderMarkingScanService

    @staticmethod
    def _require_mode_permission(*, request, order, mode: str):
        if order.table_session_id:
            require_any_permission_code(request.user, POS_TABLES_MANAGE_PERMISSION)
            return

        if mode == 'remove':
            require_any_permission_code(
                request.user,
                POS_TAKEAWAY_MENU_VIEW_PERMISSION,
                POS_PAYMENT_ORDER_ITEMS_DELETE_PERMISSION,
            )
            return

        if mode == 'attach':
            require_any_permission_code(
                request.user,
                POS_TAKEAWAY_MENU_VIEW_PERMISSION,
                POS_PAYMENTS_CREATE_PERMISSION,
            )
            return

        require_any_permission_code(
            request.user,
            POS_TAKEAWAY_MENU_VIEW_PERMISSION,
            POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION,
        )

    def post(self, request, order_id):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.filter(restaurant=restaurant)
            .select_related('restaurant')
            .prefetch_related('items__catalog_item', 'items__markings'),
            pk=order_id,
        )
        mode = str(request.data.get('mode') or 'add').strip().lower()
        self._require_mode_permission(request=request, order=order, mode=mode)
        self.scan_service_class().scan(
            order=order,
            raw_code=request.data.get('raw_code') or request.data.get('rawCode') or '',
            scanned_by=request.user,
            mode=mode,
        )
        order.refresh_from_db()
        order = (
            Order.objects.filter(pk=order.pk)
            .select_related('table_session', 'table_session__hall', 'table_session__table', 'opened_by', 'cashier')
            .prefetch_related('items__catalog_item', 'items__prep_station', 'items__markings', 'payments', 'receipts')
            .get()
        )
        return Response({'order': OrderSerializer(order).data, 'marking_status': marking_status(order)})


class OrderMarkingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get(self, request, order_id):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.filter(restaurant=restaurant).prefetch_related('items__catalog_item', 'items__markings'),
            pk=order_id,
        )
        return Response(marking_status(order))
