from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers
from django.utils import timezone

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.floor.services import restaurant_has_multiple_active_zones
from apps.sales.helpers import get_order_item_model, get_order_model

Order = get_order_model()
OrderItem = get_order_item_model()
Payment = get_payment_model()
Receipt = get_receipt_model()


class OpenCheckPaginationQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, default=1)
    page_size = serializers.IntegerField(required=False, default=25)


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
            'sale_unit',
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
            'cash_amount',
            'card_amount',
            'fiscal_cash_amount',
            'fiscal_card_amount',
            'fiscal_adjustment_reason',
            'status',
            'register_fiscal',
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
            'print_document',
            'kind',
            'status',
            'payload',
            'fiscal_requested_at',
            'fiscal_registered_at',
            'original_paid_at',
            'fiscal_error_code',
            'fiscal_error_message',
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
    table_number = serializers.IntegerField(source='table_session.table.table_number', read_only=True)
    hall_name = serializers.CharField(source='table_session.hall.name', read_only=True)
    zone_name = serializers.CharField(source='table_session.hall.zone_or_cabin.name', read_only=True)
    show_zone_name = serializers.SerializerMethodField()
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True)
    service_fee = serializers.SerializerMethodField()
    service_fee_enabled = serializers.SerializerMethodField()
    service_fee_percent = serializers.SerializerMethodField()
    service_fee_components = serializers.SerializerMethodField()
    service_fee_billable_minutes = serializers.SerializerMethodField()
    service_fee_quote = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    vat_enabled = serializers.SerializerMethodField()
    vat_percent = serializers.SerializerMethodField()
    vat_amount = serializers.SerializerMethodField()

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

    def _service_fee_as_of(self, obj):
        if obj.service_fee_frozen_at is not None:
            return obj.service_fee_frozen_at
        cache = getattr(self, '_service_fee_quote_times', None)
        if cache is None:
            cache = self._service_fee_quote_times = {}
        if obj.pk not in cache:
            cache[obj.pk] = timezone.now()
        return cache[obj.pk]

    def get_service_fee(self, obj):
        return obj.get_service_fee_amount(as_of=self._service_fee_as_of(obj))

    @staticmethod
    def get_service_fee_percent(obj):
        return obj.service_fee_percent

    @staticmethod
    def get_service_fee_enabled(obj):
        return obj.service_fee_enabled

    def get_service_fee_components(self, obj):
        return obj.get_service_fee_components(as_of=self._service_fee_as_of(obj))

    def get_service_fee_billable_minutes(self, obj):
        return obj.get_service_fee_billable_minutes(as_of=self._service_fee_as_of(obj))

    def get_service_fee_quote(self, obj):
        if not obj.has_hourly_service_fee:
            return None
        as_of = self._service_fee_as_of(obj)
        return {
            'quoted_at': as_of,
            'billable_minutes': obj.get_service_fee_billable_minutes(as_of=as_of),
            'service_fee': obj.get_service_fee_amount(as_of=as_of),
            'calculated_total': obj.get_calculated_total(as_of=as_of),
        }

    def get_total(self, obj):
        return obj.get_total(as_of=self._service_fee_as_of(obj))

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

    @staticmethod
    def get_vat_enabled(obj):
        return bool(getattr(obj.restaurant, 'vat_enabled', False))

    def get_vat_percent(self, obj):
        if not self.get_vat_enabled(obj):
            return 0
        return getattr(obj.restaurant, 'vat_percent', 0) or 0

    def get_vat_amount(self, obj):
        if not self.get_vat_enabled(obj):
            return 0
        return self._included_vat_amount(amount=self.get_total(obj), percent=self.get_vat_percent(obj))

    class Meta:
        model = Order
        fields = (
            'id',
            'table_session',
            'table_id',
            'table_name',
            'table_number',
            'hall_name',
            'zone_name',
            'show_zone_name',
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
            'service_fee_enabled',
            'service_fee_percent',
            'service_fee_components',
            'service_fee_billable_minutes',
            'service_fee_quote',
            'restaurant_service_fee_percent',
            'hall_service_fee_percent',
            'table_service_fee_percent',
            'service_fee_started_at',
            'service_fee_frozen_at',
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
