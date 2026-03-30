from django.db import transaction
from rest_framework import generics, permissions

from apps.orders.models import Order, OrderItem
from apps.orders.serializers import OrderItemSerializer
from apps.orders.services import OrderStateService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class OrderItemListCreateView(generics.ListCreateAPIView):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'orders.manage'
    state_service_class = OrderStateService

    def get_queryset(self):
        branch = get_request_branch(self.request)
        order_id = self.kwargs['order_id']
        return OrderItem.objects.filter(order__branch=branch, order_id=order_id).select_related('catalog_item', 'prep_station')

    @transaction.atomic
    def perform_create(self, serializer):
        branch = get_request_branch(self.request)
        order = generics.get_object_or_404(Order, pk=self.kwargs['order_id'], branch=branch)
        self.state_service_class().ensure_order_mutable(order=order)
        serializer.save(order=order, created_by=self.request.user)
        self.state_service_class().sync_after_items_changed(order=order)
