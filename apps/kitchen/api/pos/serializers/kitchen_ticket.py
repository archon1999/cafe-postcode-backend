from rest_framework import serializers

from apps.kitchen.models import KitchenTicket
from .order_item import OrderItemSerializer
from apps.sales.helpers import get_order_item_model

OrderItem = get_order_item_model()


class KitchenTicketSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    hall_name = serializers.CharField(source='order.table_session.hall.name', read_only=True)
    table_name = serializers.CharField(source='order.table_session.table.name', read_only=True)
    waiter_name = serializers.CharField(source='order.opened_by.full_name', read_only=True)
    items = serializers.SerializerMethodField()

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
            'prep_station',
            'prep_station_name',
            'status',
            'routed_via',
            'is_printed',
            'printed_payload',
            'hall_name',
            'table_name',
            'waiter_name',
            'items',
            'completed_at',
            'created_at',
        )
