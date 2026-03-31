from django.db import transaction
from rest_framework import generics, permissions

from apps.orders.models import OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.orders.services import OrderStateService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class OrderItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'orders.manage'
    state_service_class = OrderStateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return OrderItem.objects.filter(order__restaurant=restaurant).select_related('catalog_item', 'prep_station', 'order')

    @transaction.atomic
    def perform_update(self, serializer):
        self.state_service_class().ensure_order_mutable(order=serializer.instance.order)
        instance = serializer.save()
        self.state_service_class().sync_after_items_changed(order=instance.order)

    @transaction.atomic
    def perform_destroy(self, instance):
        order = instance.order
        self.state_service_class().ensure_order_mutable(order=order)
        instance.delete()
        self.state_service_class().sync_after_items_changed(order=order)
