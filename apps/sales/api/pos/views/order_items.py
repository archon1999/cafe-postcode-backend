from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.models import KitchenTicket
from apps.printing.services import create_kitchen_cancellation_print_document
from apps.sales.helpers import get_order_item_model, get_order_model
from apps.sales.serializers import OrderItemSerializer
from apps.sales.services import OrderStateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION,
    POS_PAYMENT_ORDER_ITEMS_DELETE_PERMISSION,
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
        order = generics.get_object_or_404(
            Order.objects.select_for_update(),
            pk=self.kwargs['order_id'],
            restaurant=restaurant,
        )
        if order.table_session_id:
            require_any_permission_code(self.request.user, POS_TABLES_MANAGE_PERMISSION)
        else:
            require_any_permission_code(
                self.request.user,
                POS_TAKEAWAY_MENU_VIEW_PERMISSION,
                POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION,
            )
        state_service = self.state_service_class()
        state_service.ensure_order_mutable(order=order)
        state_service.ensure_catalog_item_matches_order(
            catalog_item=serializer.validated_data.get('catalog_item'),
            order=order,
        )
        serializer.save(
            order=order,
            created_by=self.request.user,
            status=OrderItem.Status.NEW,
        )
        state_service.sync_after_items_changed(order=order)
        self.kitchen_print_documents = []

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        payload = dict(response.data)
        payload['kitchenPrintDocuments'] = getattr(self, 'kitchen_print_documents', [])
        response.data = payload
        return response


class OrderItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return OrderItem.objects.filter(order__restaurant=restaurant).select_related('catalog_item', 'prep_station', 'order')

    @transaction.atomic
    def perform_update(self, serializer):
        order = (
            Order.objects.select_for_update()
            .select_related('restaurant')
            .get(pk=serializer.instance.order_id)
        )
        locked_item = (
            OrderItem.objects.select_for_update()
            .select_related('catalog_item', 'order')
            .get(pk=serializer.instance.pk, order=order)
        )
        serializer.instance = locked_item
        required_permission = (
            POS_TABLES_MANAGE_PERMISSION
            if order.table_session_id
            else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        )
        require_any_permission_code(self.request.user, required_permission)
        state_service = self.state_service_class()
        state_service.ensure_order_mutable(order=order)
        serializer.validate_update_constraints(
            instance=locked_item,
            attrs=serializer.validated_data,
        )
        state_service.ensure_catalog_item_matches_order(
            catalog_item=serializer.validated_data.get(
                'catalog_item',
                locked_item.catalog_item,
            ),
            order=order,
        )
        instance = serializer.save()
        state_service.sync_after_items_changed(order=order)

    @transaction.atomic
    def perform_destroy(self, instance):
        order = (
            Order.objects.select_for_update()
            .get(pk=instance.order_id)
        )
        instance = (
            OrderItem.objects.select_for_update()
            .select_related('order')
            .get(pk=instance.pk, order=order)
        )
        if order.table_session_id:
            require_any_permission_code(self.request.user, POS_TABLES_MANAGE_PERMISSION)
        else:
            require_any_permission_code(
                self.request.user,
                POS_TAKEAWAY_MENU_VIEW_PERMISSION,
                POS_PAYMENT_ORDER_ITEMS_DELETE_PERMISSION,
            )
        state_service = self.state_service_class()
        state_service.ensure_order_mutable(order=order)
        original_ticket = (
            KitchenTicket.objects.select_for_update()
            .filter(lines__order_item=instance)
            .first()
        )
        requires_cancellation_print = bool(
            original_ticket
            and original_ticket.routed_via
            in (KitchenTicket.RouteMode.PRINTER, KitchenTicket.RouteMode.BOTH)
        )
        state_service.remove_order_item(order_item=instance)
        state_service.sync_after_items_changed(order=order)
        self.kitchen_print_documents = []
        if requires_cancellation_print:
            document, _snapshot = create_kitchen_cancellation_print_document(
                ticket=original_ticket,
                order_item=instance,
                quantity_delta=-instance.quantity,
                created_by=self.request.user,
            )
            self.kitchen_print_documents.append(str(document.id))

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        documents = getattr(self, 'kitchen_print_documents', [])
        if not documents:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {
                'kitchenPrintDocuments': documents,
            },
            status=status.HTTP_200_OK,
        )


class BulkOrderItemCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    state_service_class = OrderStateService

    @transaction.atomic
    def post(self, request, order_id):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(
            Order.objects.select_for_update(),
            pk=order_id,
            restaurant=restaurant,
        )
        if order.table_session_id:
            require_any_permission_code(request.user, POS_TABLES_MANAGE_PERMISSION)
        else:
            require_any_permission_code(
                request.user,
                POS_TAKEAWAY_MENU_VIEW_PERMISSION,
                POS_PAYMENT_ORDER_ITEMS_CREATE_PERMISSION,
            )

        payloads = request.data.get('items', []) if isinstance(request.data, dict) else []
        if not isinstance(payloads, list) or not payloads:
            return Response({'items': ['At least one item is required.']}, status=status.HTTP_400_BAD_REQUEST)
        if len(payloads) > 100:
            return Response({'items': ['At most 100 configurations can be added at once.']}, status=status.HTTP_400_BAD_REQUEST)

        item_serializers = [OrderItemSerializer(data=payload, context={'request': request}) for payload in payloads]
        errors = {}
        for index, serializer in enumerate(item_serializers):
            if not serializer.is_valid():
                errors[index] = serializer.errors
        if errors:
            return Response({'items': errors}, status=status.HTTP_400_BAD_REQUEST)

        state_service = self.state_service_class()
        state_service.ensure_order_mutable(order=order)
        for serializer in item_serializers:
            state_service.ensure_catalog_item_matches_order(
                catalog_item=serializer.validated_data.get('catalog_item'),
                order=order,
            )
        created_items = [
            serializer.save(
                order=order,
                created_by=request.user,
                status=OrderItem.Status.NEW,
            )
            for serializer in item_serializers
        ]
        state_service.sync_after_items_changed(order=order)
        return Response(
            {
                'items': OrderItemSerializer(created_items, many=True).data,
                'kitchenPrintDocuments': [],
            },
            status=status.HTTP_201_CREATED,
        )


__all__ = ['BulkOrderItemCreateView', 'OrderItemDetailView', 'OrderItemListCreateView']
