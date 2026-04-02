from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import Role
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order
from apps.organizations.models import CashDesk, Device, DistributionPoint, FeatureConfig, PrepStation, Restaurant
from common.api.scopes import get_request_restaurant


ACTIVE_ORDER_STATUSES = {
    Order.Status.OPEN,
    Order.Status.SUBMITTED,
    Order.Status.READY,
}


def _get_prefetched_related(instance, relation_name):
    return getattr(instance, '_prefetched_objects_cache', {}).get(relation_name)


def _resolve_serializer_restaurant(serializer, attrs):
    restaurant = attrs.get('restaurant') or getattr(serializer.instance, 'restaurant', None)
    if restaurant is not None:
        return restaurant

    request = serializer.context.get('request')
    if request is None:
        return None

    return get_request_restaurant(request)


def resolve_service_state(session: TableSession) -> str:
    if session.status == TableSession.Status.PENDING_PAYMENT:
        return 'pending_payment'

    prefetched_orders = _get_prefetched_related(session, 'orders')
    if prefetched_orders is None:
        active_orders = session.orders.filter(status__in=ACTIVE_ORDER_STATUSES).order_by('-created_at')
        latest_order = active_orders.first()
    else:
        active_orders = [order for order in prefetched_orders if order.status in ACTIVE_ORDER_STATUSES]
        latest_order = max(active_orders, key=lambda order: order.created_at, default=None)

    if latest_order is None:
        return 'done'

    prefetched_tickets = _get_prefetched_related(latest_order, 'kitchen_tickets')
    if prefetched_tickets is None:
        tickets = list(latest_order.kitchen_tickets.all())
    else:
        tickets = list(prefetched_tickets)

    if any(ticket.status == KitchenTicket.Status.COOKING for ticket in tickets):
        return 'cooking'

    if any(ticket.status == KitchenTicket.Status.NEW for ticket in tickets):
        return 'new'

    return 'done'


class FeatureConfigSerializer(serializers.ModelSerializer):
    restaurant = serializers.PrimaryKeyRelatedField(queryset=Restaurant.objects.all(), required=False)
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)
    enabled_role_details = serializers.SerializerMethodField()

    class Meta:
        model = FeatureConfig
        fields = (
            'id',
            'restaurant',
            'restaurant_name',
            'hall_enabled',
            'kitchen_enabled',
            'cashier_enabled',
            'owner_dashboard_enabled',
            'order_entry_mode',
            'kitchen_mode',
            'enabled_modules',
            'enabled_roles',
            'enabled_role_details',
        )

    def get_enabled_role_details(self, obj):
        role_codes = list(obj.enabled_roles or [])

        if not role_codes:
            return []

        roles_by_code = {
            role.code: {'id': str(role.id), 'code': role.code, 'name': role.name}
            for role in Role.objects.filter(code__in=role_codes)
        }

        return [roles_by_code.get(role_code, {'id': '', 'code': role_code, 'name': role_code}) for role_code in role_codes]


class ActiveSessionSummarySerializer(serializers.ModelSerializer):
    service_state = serializers.SerializerMethodField()

    class Meta:
        model = TableSession
        fields = ('id', 'guest_count', 'status', 'assigned_waiter_id', 'created_at', 'service_state')

    def get_service_state(self, obj):
        return resolve_service_state(obj)


class ZoneOrCabinSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZoneOrCabin
        fields = ('id', 'name', 'sort_order', 'is_active')


class DiningTableSerializer(serializers.ModelSerializer):
    active_session = serializers.SerializerMethodField()
    hall_name = serializers.CharField(source='hall.name', read_only=True)
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model = DiningTable
        fields = (
            'id',
            'hall',
            'hall_name',
            'zone',
            'zone_name',
            'name',
            'table_number',
            'seat_count',
            'shape',
            'shape_variant',
            'status',
            'position_x',
            'position_y',
            'width',
            'height',
            'rotation',
            'is_active',
            'active_session',
        )

    def get_active_session(self, obj):
        prefetched_sessions = getattr(obj, '_prefetched_objects_cache', {}).get('table_sessions')
        if prefetched_sessions is None:
            session = (
                obj.table_sessions.filter(status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT])
                .order_by('-created_at')
                .first()
            )
        else:
            active_sessions = [
                session
                for session in prefetched_sessions
                if session.status in [TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT]
            ]
            session = max(active_sessions, key=lambda item: item.created_at, default=None)

        if session is None:
            return None
        return ActiveSessionSummarySerializer(session).data

    def validate_seat_count(self, value):
        if value not in DiningTable.get_supported_seat_counts():
            raise serializers.ValidationError(_('Only 2, 3, 4, 5, or 6 seat tables are supported.'))
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        hall = attrs.get('hall', getattr(self.instance, 'hall', None))

        if hall is not None:
            attrs['zone'] = hall.zone_or_cabin

        seat_count = attrs.get('seat_count', getattr(self.instance, 'seat_count', 4))
        shape_variant = attrs.get(
            'shape_variant',
            getattr(self.instance, 'shape_variant', DiningTable.get_default_shape_variant(seat_count)),
        )

        if shape_variant not in DiningTable.get_supported_variants_for_seat_count(seat_count):
            raise serializers.ValidationError({'shape_variant': _('Shape variant does not match the selected seat count.')})

        attrs['shape_variant'] = shape_variant
        if 'shape' not in attrs:
            attrs['shape'] = DiningTable.infer_shape_from_variant(shape_variant)
        return attrs


class HallSerializer(serializers.ModelSerializer):
    zone_or_cabin_id = serializers.PrimaryKeyRelatedField(source='zone_or_cabin', queryset=ZoneOrCabin.objects.all())
    zone_or_cabin = ZoneOrCabinSerializer(read_only=True)
    tables = DiningTableSerializer(many=True, read_only=True)

    class Meta:
        model = Hall
        fields = (
            'id',
            'name',
            'description',
            'grid_columns',
            'sort_order',
            'is_active',
            'zone_or_cabin_id',
            'zone_or_cabin',
            'tables',
        )
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        restaurant = get_request_restaurant(request) if request is not None else getattr(self.instance, 'restaurant', None)
        zone_or_cabin = attrs.get('zone_or_cabin', getattr(self.instance, 'zone_or_cabin', None))

        if zone_or_cabin is not None and restaurant is not None and zone_or_cabin.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'zoneOrCabinId': _('Selected zone does not belong to the current restaurant.')})

        if self.instance is not None and zone_or_cabin is not None and self.instance.tables.exclude(zone=zone_or_cabin).exists():
            raise serializers.ValidationError({'zoneOrCabinId': _('Reassign or remove tables before changing the zone or cabin.')})

        return attrs

    def update(self, instance, validated_data):
        hall = super().update(instance, validated_data)
        hall.tables.exclude(zone=hall.zone_or_cabin).update(zone=hall.zone_or_cabin)
        return hall


class PrepStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrepStation
        fields = ('id', 'name', 'kind', 'is_active')


class CashDeskSerializer(serializers.ModelSerializer):
    def validate_enabled_payment_methods(self, value):
        allowed_values = {'cash', 'card', 'qr'}
        values = list(dict.fromkeys(value or []))
        if not values:
            raise serializers.ValidationError(_('At least one payment method must be enabled.'))
        if any(item not in allowed_values for item in values):
            raise serializers.ValidationError(_('Unsupported payment method selected.'))
        return values

    class Meta:
        model = CashDesk
        fields = (
            'id',
            'name',
            'location',
            'enabled_payment_methods',
            'fiscal_provider',
            'receipt_printer_enabled',
            'terminal_id',
            'external_cashbox_id',
            'is_active',
        )


class DeviceSerializer(serializers.ModelSerializer):
    primary_hall_id = serializers.PrimaryKeyRelatedField(
        source='primary_hall',
        queryset=Hall.objects.all(),
        required=False,
        allow_null=True,
    )
    primary_hall_name = serializers.CharField(source='primary_hall.name', read_only=True)
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_halls',
        queryset=Hall.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Device
        fields = (
            'id',
            'name',
            'mode',
            'primary_hall_id',
            'primary_hall_name',
            'allowed_hall_ids',
            'is_active',
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        restaurant = _resolve_serializer_restaurant(self, attrs)
        primary_hall = attrs.get('primary_hall', getattr(self.instance, 'primary_hall', None))

        if 'allowed_halls' in attrs:
            allowed_halls = list(attrs['allowed_halls'])
        elif self.instance:
            allowed_halls = list(self.instance.allowed_halls.all())
        else:
            allowed_halls = []

        if primary_hall is not None and restaurant is not None and primary_hall.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'primaryHallId': _('Selected hall does not belong to the selected restaurant.')})

        if restaurant is not None and any(hall.restaurant_id != restaurant.id for hall in allowed_halls):
            raise serializers.ValidationError({'allowedHallIds': _('All allowed halls must belong to the selected restaurant.')})

        if primary_hall is not None and not any(hall.id == primary_hall.id for hall in allowed_halls):
            allowed_halls.append(primary_hall)

        attrs['allowed_halls'] = allowed_halls
        return attrs

    def create(self, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', [])
        device = super().create(validated_data)
        if allowed_halls:
            device.allowed_halls.set(allowed_halls)
        return device

    def update(self, instance, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', None)
        device = super().update(instance, validated_data)
        if allowed_halls is not None:
            device.allowed_halls.set(allowed_halls)
        return device


class DistributionPointSerializer(serializers.ModelSerializer):
    assigned_hall_name = serializers.CharField(source='assigned_hall.name', read_only=True)

    class Meta:
        model = DistributionPoint
        fields = (
            'id',
            'name',
            'kind',
            'integration_channel',
            'assigned_hall',
            'assigned_hall_name',
            'is_active',
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        restaurant = _resolve_serializer_restaurant(self, attrs)
        assigned_hall = attrs.get('assigned_hall', getattr(self.instance, 'assigned_hall', None))

        if assigned_hall is not None and restaurant is not None and assigned_hall.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'assignedHall': _('Selected hall does not belong to the selected restaurant.')})

        return attrs


class TableSessionSerializer(serializers.ModelSerializer):
    hall_name = serializers.CharField(source='hall.name', read_only=True)
    table_name = serializers.CharField(source='table.name', read_only=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    assigned_waiter_name = serializers.CharField(source='assigned_waiter.full_name', read_only=True)

    class Meta:
        model = TableSession
        fields = (
            'id',
            'hall',
            'hall_name',
            'table',
            'table_name',
            'opened_by',
            'opened_by_name',
            'assigned_waiter',
            'assigned_waiter_name',
            'guest_count',
            'status',
            'note',
            'merged_into',
            'closed_at',
            'created_at',
        )

    def validate(self, attrs):
        hall = attrs.get('hall') or getattr(self.instance, 'hall', None)
        table = attrs.get('table') or getattr(self.instance, 'table', None)

        if hall and table and table.hall_id != hall.id:
            raise serializers.ValidationError({'table': _('Selected table does not belong to the selected hall.')})

        return attrs


class RestaurantSerializer(serializers.ModelSerializer):
    feature_config = FeatureConfigSerializer(read_only=True)

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'legal_name',
            'tax_number',
            'phone',
            'address',
            'currency',
            'auth_code',
            'is_active',
            'feature_config',
        )
        extra_kwargs = {'currency': {'required': False}}

    def create(self, validated_data):
        validated_data['currency'] = 'UZS'
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['currency'] = 'UZS'
        return super().update(instance, validated_data)
