from rest_framework import serializers

from apps.kitchen.models import KitchenTicket
from apps.kitchen.api.admin.serializers import OrderItemSerializer
class KitchenTicketSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    prep_station_name = serializers.CharField(
        source="prep_station.name", read_only=True
    )
    order_number = serializers.IntegerField(source="order.order_number", read_only=True)
    order_display_name = serializers.CharField(
        source="order.display_name", read_only=True
    )
    hall_name = serializers.CharField(
        source="order.table_session.hall.name", read_only=True
    )
    table_name = serializers.CharField(
        source="order.table_session.table.name", read_only=True
    )
    waiter_name = serializers.CharField(
        source="order.opened_by.full_name", read_only=True
    )
    items = serializers.SerializerMethodField()

    def get_items(self, obj):
        prefetched_lines = getattr(obj, "_prefetched_objects_cache", {}).get("lines")
        if prefetched_lines is not None:
            items = [line.order_item for line in prefetched_lines]
        else:
            items = [
                line.order_item
                for line in obj.lines.select_related("order_item__catalog_item", "order_item__prep_station")
            ]
        if not items:
            items = list(
                obj.order.items.filter(prep_station=obj.prep_station)
                .exclude(status="cancelled")
                .select_related("catalog_item", "prep_station")
            )
        return OrderItemSerializer(items, many=True).data

    class Meta:
        model = KitchenTicket
        fields = (
            "id",
            "restaurant_name",
            "order",
            "order_number",
            "order_display_name",
            "prep_station",
            "prep_station_name",
            "dispatch_number",
            "status",
            "routed_via",
            "is_printed",
            "printed_payload",
            "hall_name",
            "table_name",
            "waiter_name",
            "items",
            "completed_at",
            "handed_off_at",
            "created_at",
        )
