from django.db import transaction
from rest_framework import generics, permissions

from apps.orders.models import Order, OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.orders.services import OrderStateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


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
        self.state_service_class().ensure_order_mutable(order=order)
        serializer.save(order=order, created_by=self.request.user)
        self.state_service_class().sync_after_items_changed(order=order)
