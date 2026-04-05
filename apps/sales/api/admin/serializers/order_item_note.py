from rest_framework import serializers

from apps.sales.helpers import get_order_item_note_model

OrderItemNote = get_order_item_note_model()


class AdminOrderItemNoteSerializer(serializers.ModelSerializer):
    order_item_id = serializers.UUIDField(source='order_item_id', read_only=True)
    order_id = serializers.UUIDField(source='order_item.order_id', read_only=True)
    order_number = serializers.IntegerField(source='order_item.order.order_number', read_only=True)
    catalog_item_name = serializers.CharField(source='order_item.catalog_item.name', read_only=True)
    table_name = serializers.CharField(source='order_item.order.table_session.table.name', read_only=True)

    class Meta:
        model = OrderItemNote
        fields = (
            'id',
            'order_item_id',
            'order_id',
            'order_number',
            'catalog_item_name',
            'table_name',
            'body',
            'created_at',
            'updated_at',
        )
