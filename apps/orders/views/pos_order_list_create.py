from django.db import transaction
from rest_framework import generics, permissions

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.orders.services import OrderStateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class PosOrderListCreateView(generics.ListCreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        queryset = Order.objects.filter(restaurant=restaurant).select_related(
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
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        state_service = self.state_service_class()
        table_session = serializer.validated_data.get('table_session')
        channel = serializer.validated_data.get('channel', Order.Channel.HALL)
        required_permission = POS_TABLES_MANAGE_PERMISSION if table_session or channel == Order.Channel.HALL else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(self.request.user, required_permission)
        state_service.ensure_session_accepts_new_order(table_session=table_session)
        serializer.save(
            restaurant=restaurant,
            opened_by=self.request.user,
            guest_count=table_session.guest_count if table_session else serializer.validated_data.get('guest_count', 1),
            order_number=state_service.next_order_number(restaurant=restaurant),
        )
