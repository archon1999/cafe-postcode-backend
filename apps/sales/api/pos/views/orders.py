from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.helpers import get_order_model
from apps.sales.serializers import OrderSerializer
from apps.sales.services import OrderStateService, OrderSubmissionService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant

Order = get_order_model()


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


class PosOrderDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    rename_allowed_statuses = {Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY}

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

    def ensure_order_can_update_display_name(self, request, order: Order):
        if 'display_name' not in request.data:
            return
        if order.status not in self.rename_allowed_statuses:
            raise ValidationError({'displayName': [_('Only open orders can be renamed.')]})

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        require_any_permission_code(request.user, self.get_required_permission(order))
        self.ensure_order_can_update_display_name(request, order)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        require_any_permission_code(request.user, self.get_required_permission(order))
        self.ensure_order_can_update_display_name(request, order)
        return super().partial_update(request, *args, **kwargs)


class OrderSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_submission_service_class = OrderSubmissionService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(Order, pk=pk, restaurant=restaurant)
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(request.user, required_permission)
        if not order.items.exists():
            return Response({'detail': _('Order has no items.')}, status=status.HTTP_400_BAD_REQUEST)
        self.order_submission_service_class().submit(order)
        return Response(OrderSerializer(order).data)

__all__ = ['OrderSubmitView', 'PosOrderDetailView', 'PosOrderListCreateView']
