from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.helpers import get_order_model
from apps.sales.selectors.orders import pos_order_queryset
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
        queryset = pos_order_queryset(Order.objects.filter(restaurant=restaurant))
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        state_service = self.state_service_class()
        table_session = serializer.validated_data.get('table_session')
        channel = Order.Channel.HALL if table_session else serializer.validated_data.get('channel', Order.Channel.HALL)
        if table_session:
            required_permissions = (POS_TABLES_MANAGE_PERMISSION,)
        elif channel == Order.Channel.HALL:
            required_permissions = (POS_TAKEAWAY_MENU_VIEW_PERMISSION, POS_TABLES_MANAGE_PERMISSION)
        else:
            required_permissions = (POS_TAKEAWAY_MENU_VIEW_PERMISSION,)
        require_any_permission_code(self.request.user, *required_permissions)
        state_service.ensure_table_session_matches_restaurant(
            table_session=table_session,
            restaurant=restaurant,
        )
        state_service.ensure_session_accepts_new_order(table_session=table_session)
        distribution_point = serializer.validated_data.get('distribution_point')
        state_service.ensure_distribution_point_matches_order(
            distribution_point=distribution_point,
            restaurant=restaurant,
            channel=channel,
        )
        if distribution_point is None:
            distribution_point = state_service.resolve_distribution_point(
                restaurant=restaurant,
                channel=channel,
                table_session=table_session,
            )
        order_number = state_service.next_order_number(restaurant=restaurant)
        requested_display_name = serializer.validated_data.get('display_name') or ''
        trusted_edge_replay = bool(getattr(self.request._request, 'trusted_edge_replay', False))
        if trusted_edge_replay:
            display_name = state_service.reconcile_shift_display_name(
                restaurant=restaurant,
                user=self.request.user,
                requested_display_name=requested_display_name,
            )
        else:
            display_name = requested_display_name or state_service.next_shift_display_name(
                restaurant=restaurant,
                user=self.request.user,
            )
        order = serializer.save(
            restaurant=restaurant,
            opened_by=self.request.user,
            distribution_point=distribution_point,
            channel=channel,
            guest_count=table_session.guest_count if table_session else serializer.validated_data.get('guest_count', 1),
            order_number=order_number,
            display_name=display_name or str(order_number),
            status=Order.Status.OPEN,
        )
        edge_occurred_at = getattr(self.request._request, 'trusted_edge_occurred_at', None)
        if trusted_edge_replay and edge_occurred_at is not None:
            Order.objects.filter(pk=order.pk).update(created_at=edge_occurred_at)
            order.created_at = edge_occurred_at


class PosOrderDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService
    rename_allowed_statuses = {Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY}

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return pos_order_queryset(Order.objects.filter(restaurant=restaurant))

    def get_required_permission(self, order: Order) -> str:
        return POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION

    def ensure_order_can_update_display_name(self, request, order: Order):
        if 'display_name' not in request.data:
            return
        if order.status not in self.rename_allowed_statuses:
            raise ValidationError({'displayName': [_('Only open orders can be renamed.')]})

    def ensure_order_can_update_channel(self, request, order: Order):
        if 'channel' not in request.data:
            return
        if order.table_session_id:
            raise ValidationError({'channel': [_('Table orders cannot change channel.')]})
        if order.status != Order.Status.OPEN or order.payments.exists():
            raise ValidationError({'channel': [_('Only unpaid open counter orders can change channel.')]})

    @transaction.atomic
    def perform_update(self, serializer):
        locked_order = (
            Order.objects.select_for_update()
            .select_related('restaurant')
            .get(pk=serializer.instance.pk, restaurant_id=serializer.instance.restaurant_id)
        )
        serializer.instance = locked_order
        require_any_permission_code(self.request.user, self.get_required_permission(locked_order))
        self.ensure_order_can_update_display_name(self.request, locked_order)
        self.ensure_order_can_update_channel(self.request, locked_order)
        state_service = self.state_service_class()
        state_service.ensure_order_mutable(order=locked_order)
        channel = serializer.validated_data.get('channel', locked_order.channel)
        table_session = locked_order.table_session
        state_service.ensure_table_session_matches_restaurant(
            table_session=table_session,
            restaurant=locked_order.restaurant,
        )
        updates = {}
        if channel != locked_order.channel:
            updates['distribution_point'] = state_service.resolve_distribution_point(
                restaurant=locked_order.restaurant,
                channel=channel,
            )
            if channel != Order.Channel.DELIVERY:
                updates['delivery_phone'] = ''
                updates['delivery_address'] = ''
        else:
            state_service.ensure_distribution_point_matches_order(
                distribution_point=serializer.validated_data.get(
                    'distribution_point',
                    locked_order.distribution_point,
                ),
                restaurant=locked_order.restaurant,
                channel=channel,
            )
        serializer.save(**updates)

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        require_any_permission_code(request.user, self.get_required_permission(order))
        self.ensure_order_can_update_display_name(request, order)
        self.ensure_order_can_update_channel(request, order)
        self.state_service_class().ensure_order_mutable(order=order)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)


class OrderSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_submission_service_class = OrderSubmissionService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.select_for_update(of=('self',)), pk=pk, restaurant=restaurant
        )
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(request.user, required_permission)
        if not order.items.exists():
            return Response({'detail': _('Order has no items.')}, status=status.HTTP_400_BAD_REQUEST)
        created_tickets = self.order_submission_service_class().submit(order)
        order = generics.get_object_or_404(
            pos_order_queryset(Order.objects.filter(restaurant=restaurant)),
            pk=order.pk,
        )
        payload = dict(OrderSerializer(order).data)
        payload['kitchenPrintDocuments'] = [
            str(ticket.print_document_id)
            for ticket in created_tickets
            if ticket.routed_via in ['printer', 'both'] and ticket.print_document_id
        ]
        payload['kitchenDispatchCount'] = len(created_tickets)
        return Response(payload)


class OrderServeReadyView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.select_for_update(of=('self',)), pk=pk, restaurant=restaurant
        )
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(request.user, required_permission)
        self.state_service_class().serve_ready_items(order=order)
        order = generics.get_object_or_404(
            pos_order_queryset(Order.objects.filter(restaurant=restaurant)),
            pk=order.pk,
        )
        return Response(OrderSerializer(order).data)

__all__ = ['OrderServeReadyView', 'OrderSubmitView', 'PosOrderDetailView', 'PosOrderListCreateView']
