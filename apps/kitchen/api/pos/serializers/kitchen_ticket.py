from rest_framework import serializers

from apps.kitchen.models import KitchenTicket
from .order_item import OrderItemSerializer
from apps.sales.helpers import get_order_item_model

OrderItem = get_order_item_model()


class KitchenTicketSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    display_name = serializers.CharField(source='order.display_name', read_only=True)
    channel = serializers.CharField(source='order.channel', read_only=True)
    hall_name = serializers.CharField(source='order.table_session.hall.name', read_only=True)
    table_name = serializers.CharField(source='order.table_session.table.name', read_only=True)
    waiter_name = serializers.CharField(source='order.opened_by.full_name', read_only=True)
    items = serializers.SerializerMethodField()
    can_announce = serializers.SerializerMethodField()

    def get_can_announce(self, obj):
        if obj.status != KitchenTicket.Status.DONE:
            return False
        prefetched_tickets = getattr(obj.order, '_prefetched_objects_cache', {}).get('kitchen_tickets')
        if prefetched_tickets is not None:
            return all(ticket.status == KitchenTicket.Status.DONE for ticket in prefetched_tickets)
        return not obj.order.kitchen_tickets.exclude(status=KitchenTicket.Status.DONE).exists()

    def get_items(self, obj):
        prefetched_items = getattr(obj.order, '_prefetched_objects_cache', {}).get('items')
        if prefetched_items is not None:
            items = [
                item
                for item in prefetched_items
                if item.prep_station_id == obj.prep_station_id and item.status != OrderItem.Status.CANCELLED
            ]
            return OrderItemSerializer(items, many=True).data

        queryset = (
            obj.order.items.filter(prep_station=obj.prep_station)
            .exclude(status=OrderItem.Status.CANCELLED)
            .select_related('catalog_item', 'prep_station')
        )
        return OrderItemSerializer(queryset, many=True).data

    class Meta:
        model = KitchenTicket
        fields = (
            'id',
            'order',
            'order_number',
            'display_name',
            'channel',
            'prep_station',
            'prep_station_name',
            'status',
            'routed_via',
            'is_printed',
            'printed_payload',
            'print_document',
            'hall_name',
            'table_name',
            'waiter_name',
            'items',
            'can_announce',
            'completed_at',
            'created_at',
        )
