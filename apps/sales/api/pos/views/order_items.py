from django.db import transaction
from rest_framework import generics, permissions

from apps.sales.helpers import get_order_item_model, get_order_model
from apps.sales.serializers import OrderItemSerializer
from apps.sales.services import OrderStateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant

Order = get_order_model()
OrderItem = get_order_item_model()


class OrderItemListCreateView(generics.ListCreateAPIView):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        order_id = self.kwargs['order_id']
        return OrderItem.objects.filter(order__restaurant=restaurant, order_id=order_id).select_related('catalog_item', 'prep_station')

    @transaction.atomic
    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        order = generics.get_object_or_404(Order, pk=self.kwargs['order_id'], restaurant=restaurant)
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(self.request.user, required_permission)
        self.state_service_class().ensure_order_mutable(order=order)
        serializer.save(order=order, created_by=self.request.user)
        self.state_service_class().sync_after_items_changed(order=order)


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

__all__ = ['OrderItemDetailView', 'OrderItemListCreateView']
