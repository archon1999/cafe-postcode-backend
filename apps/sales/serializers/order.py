from decimal import Decimal, ROUND_HALF_UP
import re

from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from rest_framework import serializers

from apps.billing.serializers import PaymentSerializer, ReceiptSerializer
from apps.floor.models import TableSession
from apps.floor.services import restaurant_has_multiple_active_zones
from apps.restaurants.models import DistributionPoint
from apps.sales.helpers import get_order_model
from common.api.scopes import get_optional_request_restaurant

from .order_item import OrderItemSerializer

Order = get_order_model()
DELIVERY_PHONE_RE = re.compile(r'^\d{2}-\d{3}-\d{2}-\d{2}$')


class OrderSerializer(serializers.ModelSerializer):
    CREATE_ONLY_FIELDS = ('table_session', 'distribution_point', 'guest_count')
    SERVER_CONTROLLED_FIELDS = (
        'restaurant_service_fee_percent',
        'hall_service_fee_percent',
        'table_service_fee_percent',
        'service_fee_snapshot',
        'service_fee_started_at',
        'service_fee_frozen_at',
    )
    UPDATE_ALLOWED_FIELDS = frozenset(
        {
            'display_name',
            'note',
            'delivery_phone',
            'delivery_address',
            'channel',
        }
    )

    id = serializers.UUIDField(required=False)
    items = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True, read_only=True)
    receipts = ReceiptSerializer(many=True, read_only=True)
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
    calculated_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    vat_enabled = serializers.SerializerMethodField()
    vat_percent = serializers.SerializerMethodField()
    vat_amount = serializers.SerializerMethodField()
    payment_total_editable = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            if getattr(request.user, 'is_superuser', False):
                return
            self.fields['table_session'].queryset = TableSession.objects.none()
            self.fields['distribution_point'].queryset = DistributionPoint.objects.none()
            return

        self.fields['table_session'].queryset = TableSession.objects.filter(
            restaurant=restaurant,
            hall__zone_or_cabin__restaurant=restaurant,
            table__hall__zone_or_cabin__restaurant=restaurant,
        )
        self.fields['distribution_point'].queryset = DistributionPoint.objects.filter(
            restaurant=restaurant,
        )

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

    def validate_display_name(self, value: str) -> str:
        return value.strip()

    def validate_delivery_phone(self, value: str) -> str:
        value = (value or '').strip()
        if value and not DELIVERY_PHONE_RE.match(value):
            raise serializers.ValidationError('Delivery phone must match DD-DDD-DD-DD.')
        return value

    def validate_delivery_address(self, value: str) -> str:
        return (value or '').strip()

    def _is_trusted_edge_replay(self) -> bool:
        request = self.context.get('request')
        raw_request = getattr(request, '_request', request)
        return bool(getattr(raw_request, 'trusted_edge_replay', False))

    def validate(self, attrs):
        errors = {}
        if self.instance is None:
            if 'id' in attrs:
                if not self._is_trusted_edge_replay():
                    errors['id'] = _('Order IDs are generated by the server.')
                elif Order.objects.filter(pk=attrs['id']).exists():
                    errors['id'] = _('An order with this ID already exists.')
            requested_status = attrs.get('status', Order.Status.OPEN)
            if requested_status != Order.Status.OPEN:
                errors['status'] = _('New orders must start in the open state.')
            for field_name in self.SERVER_CONTROLLED_FIELDS:
                if field_name in attrs:
                    errors[field_name] = _('This field is captured by the server.')
        else:
            if 'status' in attrs:
                errors['status'] = _('Order status can only be changed through lifecycle actions.')
            for field_name in self.CREATE_ONLY_FIELDS:
                if field_name in attrs:
                    errors[field_name] = _('This field can only be set when the order is created.')
            if 'id' in attrs:
                errors['id'] = _('Order IDs cannot be changed.')
            for field_name in self.SERVER_CONTROLLED_FIELDS:
                if field_name in attrs:
                    errors[field_name] = _('This server snapshot cannot be changed.')
            for field_name in set(attrs) - self.UPDATE_ALLOWED_FIELDS:
                errors.setdefault(field_name, _('This field cannot be changed through generic updates.'))
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def update(self, instance, validated_data):
        channel_changed = 'channel' in validated_data and validated_data['channel'] != instance.channel
        update_fields = set(validated_data)
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        if channel_changed:
            instance.capture_service_fee_snapshot()
            update_fields.update(self.SERVER_CONTROLLED_FIELDS)
        if update_fields:
            instance.save(update_fields=[*sorted(update_fields), 'updated_at'])
        if channel_changed:
            instance.recalculate_totals()
        return instance

    def get_service_fee(self, obj):
        return obj.get_service_fee_amount(as_of=self._service_fee_as_of(obj))

    def _service_fee_as_of(self, obj):
        if obj.service_fee_frozen_at is not None:
            return obj.service_fee_frozen_at
        cache = getattr(self, '_service_fee_quote_times', None)
        if cache is None:
            cache = self._service_fee_quote_times = {}
        if obj.pk not in cache:
            cache[obj.pk] = timezone.now()
        return cache[obj.pk]

    def get_calculated_total(self, obj):
        return obj.get_calculated_total(as_of=self._service_fee_as_of(obj))

    def get_total(self, obj):
        return obj.get_total(as_of=self._service_fee_as_of(obj))

    @staticmethod
    def get_payment_total_editable(obj):
        return getattr(obj.restaurant, 'payment_total_mode', 'fixed') == 'cashier_editable'

    def get_service_fee_percent(self, obj):
        return obj.service_fee_percent

    def get_service_fee_enabled(self, obj):
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
        return self._included_vat_amount(
            amount=self.get_total(obj),
            percent=self.get_vat_percent(obj),
        )

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
