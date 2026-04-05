from rest_framework import serializers

from apps.sales.helpers import get_order_item_model

from .order_item_note import AdminOrderItemNoteSerializer

OrderItem = get_order_item_model()


class AdminOrderItemSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    catalog_item_name = serializers.CharField(source='catalog_item.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    table_name = serializers.CharField(source='order.table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='order.table_session.hall.name', read_only=True)
    notes = AdminOrderItemNoteSerializer(many=True, read_only=True)
    notes_count = serializers.SerializerMethodField()

    def get_notes_count(self, obj):
        prefetched_notes = getattr(obj, 'notes', None)
        if prefetched_notes is not None and hasattr(prefetched_notes, 'all'):
            return prefetched_notes.count()
        return obj.notes.count()

    class Meta:
        model = OrderItem
        fields = (
            'id',
            'order',
            'order_number',
            'catalog_item',
            'catalog_item_name',
            'prep_station',
            'prep_station_name',
            'created_by',
            'created_by_name',
            'table_name',
            'hall_name',
            'quantity',
            'unit_price',
            'line_total',
            'status',
            'note',
            'notes_count',
            'notes',
            'created_at',
            'updated_at',
        )
