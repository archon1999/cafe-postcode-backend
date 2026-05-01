from rest_framework import serializers

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.sales.helpers import get_order_item_model, get_order_model

Order = get_order_model()
OrderItem = get_order_item_model()
Payment = get_payment_model()
Receipt = get_receipt_model()


class OpenCheckOrderItemSerializer(serializers.ModelSerializer):
    catalog_item_name = serializers.CharField(source='catalog_item.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    class Meta:
        model = OrderItem
        fields = (
            'id',
            'order',
            'catalog_item',
            'catalog_item_name',
            'prep_station',
            'prep_station_name',
            'quantity',
            'unit_price',
            'line_total',
            'status',
            'note',
            'created_at',
        )


class OpenCheckPaymentSerializer(serializers.ModelSerializer):
    refunds_total = serializers.IntegerField(read_only=True)
    is_refunded = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = (
            'id',
            'method',
            'amount',
            'status',
            'paid_at',
            'refunds_total',
            'is_refunded',
            'created_at',
        )


class OpenCheckReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = (
            'id',
            'payment',
            'kind',
            'status',
            'payload',
            'reprint_count',
            'last_reprinted_at',
            'created_at',
        )


class OpenCheckOrderSerializer(serializers.ModelSerializer):
    items = OpenCheckOrderItemSerializer(many=True, read_only=True)
    payments = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()
    table_id = serializers.UUIDField(source='table_session.table_id', read_only=True)
    table_name = serializers.CharField(source='table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    service_fee = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()

    def include_billing(self) -> bool:
        return bool(self.context.get('include_billing'))

    def get_payments(self, obj):
        if not self.include_billing():
            return []
        return OpenCheckPaymentSerializer(obj.payments.all(), many=True).data

    def get_receipts(self, obj):
        if not self.include_billing():
            return []
        return OpenCheckReceiptSerializer(obj.receipts.all(), many=True).data

    @staticmethod
    def get_service_fee(obj):
        subtotal = obj.subtotal or 0
        total = obj.total or 0
        return max(total - subtotal, 0)

    @staticmethod
    def get_service_fee_percent(obj):
        if obj.channel != Order.Channel.HALL:
            return 0
        return getattr(obj.restaurant, 'service_fee_percent', 10) or 0

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
