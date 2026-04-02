from django.db import transaction
from rest_framework import generics, permissions

from apps.orders.models import OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.orders.services import OrderStateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class OrderItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return OrderItem.objects.filter(order__restaurant=restaurant).select_related('catalog_item', 'prep_station', 'order')

    @transaction.atomic
    def perform_update(self, serializer):
        required_permission = (
            POS_TABLES_MANAGE_PERMISSION
            if serializer.instance.order.table_session_id
            else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        )
        require_any_permission_code(self.request.user, required_permission)
        self.state_service_class().ensure_order_mutable(order=serializer.instance.order)
        instance = serializer.save()
        self.state_service_class().sync_after_items_changed(order=instance.order)

    @transaction.atomic
    def perform_destroy(self, instance):
        order = instance.order
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(self.request.user, required_permission)
        self.state_service_class().ensure_order_mutable(order=order)
        instance.delete()
        self.state_service_class().sync_after_items_changed(order=order)
