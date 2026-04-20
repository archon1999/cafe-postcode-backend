from rest_framework import serializers

from apps.billing.serializers import PaymentSerializer, ReceiptSerializer
from apps.sales.helpers import get_order_model

from .order_item import OrderItemSerializer

Order = get_order_model()


class OrderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True, read_only=True)
    receipts = ReceiptSerializer(many=True, read_only=True)
    table_id = serializers.UUIDField(source='table_session.table_id', read_only=True)
    table_name = serializers.CharField(source='table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    service_fee = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()

    def validate_display_name(self, value: str) -> str:
        return value.strip()

    def get_service_fee(self, obj):
        subtotal = obj.subtotal or 0
        total = obj.total or 0
        return max(total - subtotal, 0)

    def get_service_fee_percent(self, obj):
        if obj.channel != Order.Channel.HALL:
            return 0
        return getattr(obj.restaurant, 'service_fee_percent', 10) or 0

    def get_items(self, obj):
        item_queryset = obj.items.select_related('catalog_item', 'prep_station')
        return OrderItemSerializer(item_queryset, many=True).data

    class Meta:
        model = Order
        fields = (
            'id',
            'table_session',
            'table_id',
            'table_name',
            'hall_name',
            'distribution_point',
            'opened_by',
            'opened_by_name',
            'cashier',
            'cashier_name',
            'order_number',
            'display_name',
            'channel',
            'status',
            'guest_count',
            'note',
            'subtotal',
            'service_fee',
            'service_fee_percent',
            'total',
            'closed_at',
            'items',
            'payments',
            'receipts',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('opened_by', 'cashier', 'order_number', 'subtotal', 'total', 'closed_at')
