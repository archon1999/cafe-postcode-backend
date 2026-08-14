from rest_framework import serializers

from apps.floor.services import restaurant_has_multiple_active_zones
from apps.kitchen.models import KitchenTicket
from .order_item import OrderItemSerializer
class KitchenTicketSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    display_name = serializers.CharField(source='order.display_name', read_only=True)
    channel = serializers.CharField(source='order.channel', read_only=True)
    hall_name = serializers.CharField(source='order.table_session.hall.name', read_only=True)
    table_name = serializers.CharField(source='order.table_session.table.name', read_only=True)
    table_number = serializers.IntegerField(source='order.table_session.table.table_number', read_only=True)
    zone_name = serializers.CharField(source='order.table_session.hall.zone_or_cabin.name', read_only=True)
    show_zone_name = serializers.SerializerMethodField()
    waiter_name = serializers.CharField(source='order.opened_by.full_name', read_only=True)
    items = serializers.SerializerMethodField()
    can_announce = serializers.SerializerMethodField()
    is_addition = serializers.SerializerMethodField()

    def get_is_addition(self, obj):
        return obj.dispatch_number > 1

    def get_show_zone_name(self, obj):
        annotated_value = getattr(obj, 'has_multiple_active_zones', None)
        if annotated_value is not None:
            return bool(annotated_value)
        restaurant_id = getattr(obj, 'restaurant_id', None)
        cache = getattr(self, '_zone_visibility_cache', None)
        if cache is None:
            cache = self._zone_visibility_cache = {}
        if restaurant_id not in cache:
            cache[restaurant_id] = restaurant_has_multiple_active_zones(restaurant_id)
        return cache[restaurant_id]

    def get_can_announce(self, obj):
        if obj.status != KitchenTicket.Status.DONE:
            return False
        prefetched_tickets = getattr(obj.order, '_prefetched_objects_cache', {}).get('kitchen_tickets')
        if prefetched_tickets is not None:
            return all(ticket.status == KitchenTicket.Status.DONE for ticket in prefetched_tickets)
        return not obj.order.kitchen_tickets.exclude(status=KitchenTicket.Status.DONE).exists()

    def get_items(self, obj):
        prefetched_lines = getattr(obj, '_prefetched_objects_cache', {}).get('lines')
        if prefetched_lines is not None:
            items = [line.order_item for line in prefetched_lines]
        else:
            items = [
                line.order_item
                for line in obj.lines.select_related('order_item__catalog_item', 'order_item__prep_station')
            ]
        if not items:
            items = list(
                obj.order.items.filter(prep_station=obj.prep_station)
                .exclude(status='cancelled')
                .select_related('catalog_item', 'prep_station')
            )
        return OrderItemSerializer(items, many=True).data

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
            'dispatch_number',
            'is_addition',
            'status',
            'routed_via',
            'is_printed',
            'printed_payload',
            'print_document',
            'hall_name',
            'table_name',
            'table_number',
            'zone_name',
            'show_zone_name',
            'waiter_name',
            'items',
            'can_announce',
            'completed_at',
            'handed_off_at',
            'created_at',
        )
