from rest_framework import generics, permissions

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class PosOrderDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return Order.objects.filter(restaurant=restaurant).select_related(
            'table_session',
            'table_session__hall',
            'table_session__table',
            'opened_by',
            'cashier',
        ).prefetch_related(
            'items__catalog_item',
            'items__prep_station',
            'payments',
            'receipts',
        )

    def get_required_permission(self, order: Order) -> str:
        return POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        require_any_permission_code(request.user, self.get_required_permission(order))
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        require_any_permission_code(request.user, self.get_required_permission(order))
        return super().partial_update(request, *args, **kwargs)
