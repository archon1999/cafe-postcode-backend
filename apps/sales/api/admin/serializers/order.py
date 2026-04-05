from rest_framework import serializers

from apps.billing.api.admin.serializers import AdminPaymentSerializer, AdminReceiptSerializer
from apps.sales.helpers import get_order_model

from .order_item import AdminOrderItemSerializer

Order = get_order_model()


class AdminOrderSerializer(serializers.ModelSerializer):
    items = AdminOrderItemSerializer(many=True, read_only=True)
    payments = AdminPaymentSerializer(many=True, read_only=True)
    receipts = AdminReceiptSerializer(many=True, read_only=True)
    table_id = serializers.UUIDField(source='table_session.table_id', read_only=True)
    table_name = serializers.CharField(source='table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
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
