from rest_framework import serializers

from apps.orders.models import Order, OrderItem, OrderItemNote, Payment, Receipt


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


class AdminPaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.full_name', read_only=True)
    cash_shift_id = serializers.UUIDField(source='cash_shift_id', read_only=True)
    refunds_total = serializers.SerializerMethodField()
    is_refunded = serializers.SerializerMethodField()

    def get_refunds_total(self, obj):
        return sum(refund.amount for refund in obj.refunds.all() if refund.status == refund.Status.SUCCEEDED)

    def get_is_refunded(self, obj):
        return any(refund.status == refund.Status.SUCCEEDED for refund in obj.refunds.all())

    class Meta:
        model = Payment
        fields = (
            'id',
            'order',
            'order_number',
            'cash_desk',
            'cash_desk_name',
            'cash_shift_id',
            'received_by',
            'received_by_name',
            'method',
            'amount',
            'status',
            'external_ref',
            'provider_payload',
            'paid_at',
            'refunds_total',
            'is_refunded',
            'created_at',
            'updated_at',
        )


class AdminReceiptSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    payment_method = serializers.CharField(source='payment.method', read_only=True)
    payment_amount = serializers.IntegerField(source='payment.amount', read_only=True)

    class Meta:
        model = Receipt
        fields = (
            'id',
            'order',
            'order_number',
            'payment',
            'payment_method',
            'payment_amount',
            'kind',
            'status',
            'provider',
            'payload',
            'reprint_count',
            'last_reprinted_at',
            'created_at',
            'updated_at',
        )


class AdminOrderSerializer(serializers.ModelSerializer):
    items = AdminOrderItemSerializer(many=True, read_only=True)
    payments = AdminPaymentSerializer(many=True, read_only=True)
    receipts = AdminReceiptSerializer(many=True, read_only=True)
    table_id = serializers.UUIDField(source='table_session.table_id', read_only=True)
    table_name = serializers.CharField(source='table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
    hall_level = serializers.IntegerField(source='table_session.hall.level', read_only=True, allow_null=True)
    distribution_point_name = serializers.CharField(source='distribution_point.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    service_fee = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()
    payments_count = serializers.SerializerMethodField()
    receipts_count = serializers.SerializerMethodField()

    def get_service_fee(self, obj):
        subtotal = obj.subtotal or 0
        total = obj.total or 0
        return max(total - subtotal, 0)

    def get_items_count(self, obj):
        return obj.items.count()

    def get_payments_count(self, obj):
        return obj.payments.count()

    def get_receipts_count(self, obj):
        return obj.receipts.count()

    class Meta:
        model = Order
        fields = (
            'id',
            'table_session',
            'table_id',
            'table_name',
            'hall_name',
            'hall_level',
            'distribution_point',
            'distribution_point_name',
            'opened_by',
            'opened_by_name',
            'cashier',
            'cashier_name',
            'order_number',
            'channel',
            'status',
            'guest_count',
            'note',
            'subtotal',
            'service_fee',
            'total',
            'closed_at',
            'items_count',
            'payments_count',
            'receipts_count',
            'items',
            'payments',
            'receipts',
            'created_at',
            'updated_at',
        )
