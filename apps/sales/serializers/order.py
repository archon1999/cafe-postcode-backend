from decimal import Decimal, ROUND_HALF_UP
import re

from rest_framework import serializers

from apps.billing.serializers import PaymentSerializer, ReceiptSerializer
from apps.sales.helpers import get_order_model

from .order_item import OrderItemSerializer

Order = get_order_model()
DELIVERY_PHONE_RE = re.compile(r'^\d{2}-\d{3}-\d{2}-\d{2}$')


class OrderSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    items = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True, read_only=True)
    receipts = ReceiptSerializer(many=True, read_only=True)
    table_id = serializers.UUIDField(source='table_session.table_id', read_only=True)
    table_name = serializers.CharField(source='table_session.table.name', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    service_fee = serializers.SerializerMethodField()
    service_fee_enabled = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()
    vat_enabled = serializers.SerializerMethodField()
    vat_percent = serializers.SerializerMethodField()
    vat_amount = serializers.SerializerMethodField()
    payment_total_editable = serializers.SerializerMethodField()

    def validate_display_name(self, value: str) -> str:
        return value.strip()

    def validate_delivery_phone(self, value: str) -> str:
        value = (value or '').strip()
        if value and not DELIVERY_PHONE_RE.match(value):
            raise serializers.ValidationError('Delivery phone must match DD-DDD-DD-DD.')
        return value

    def validate_delivery_address(self, value: str) -> str:
        return (value or '').strip()

    def get_service_fee(self, obj):
        subtotal = obj.subtotal or 0
        total = obj.calculated_total or 0
        return max(total - subtotal, 0)

    @staticmethod
    def get_payment_total_editable(obj):
        return getattr(obj.restaurant, 'payment_total_mode', 'fixed') == 'cashier_editable'

    def get_service_fee_percent(self, obj):
        if not self.get_service_fee_enabled(obj):
            return 0
        return getattr(obj.restaurant, 'service_fee_percent', 10) or 0

    def get_service_fee_enabled(self, obj):
        return bool(getattr(obj.restaurant, 'service_fee_enabled', False))

    @staticmethod
    def _included_vat_amount(*, amount: int, percent) -> int:
        try:
            rate = Decimal(str(percent or 0))
        except Exception:
            return 0
        if amount <= 0 or rate <= 0:
            return 0
        included_vat = Decimal(amount) * rate / (Decimal('100') + rate)
        return int(included_vat.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def get_vat_enabled(self, obj):
        return bool(getattr(obj.restaurant, 'vat_enabled', False))

    def get_vat_percent(self, obj):
        if not self.get_vat_enabled(obj):
            return 0
        return getattr(obj.restaurant, 'vat_percent', 0) or 0

    def get_vat_amount(self, obj):
        if not self.get_vat_enabled(obj):
            return 0
        return self._included_vat_amount(amount=int(obj.total or 0), percent=self.get_vat_percent(obj))

    def get_items(self, obj):
        prefetched_items = getattr(obj, '_prefetched_objects_cache', {}).get('items')
        if prefetched_items is not None:
            return OrderItemSerializer(prefetched_items, many=True).data

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
            'delivery_phone',
            'delivery_address',
            'subtotal',
            'calculated_total',
            'total_override',
            'total_override_reason',
            'total_overridden_at',
            'payment_total_editable',
            'service_fee',
            'service_fee_enabled',
            'service_fee_percent',
            'vat_enabled',
            'vat_percent',
            'vat_amount',
            'total',
            'closed_at',
            'items',
            'payments',
            'receipts',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'opened_by',
            'cashier',
            'order_number',
            'subtotal',
            'calculated_total',
            'total_override',
            'total_override_reason',
            'total_overridden_at',
            'total',
            'closed_at',
        )
