from django.db.models import Q
from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.platform.services import get_restaurant_balance_summary
from apps.restaurants.helpers import get_restaurant_model
from apps.users.helpers import get_employee_profile_model, get_user_model

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
Tariff = get_tariff_model()
EmployeeProfile = get_employee_profile_model()
User = get_user_model()


def _restore_faktura_payload(value):
    if isinstance(value, list):
        return [_restore_faktura_payload(item) for item in value]

    if not isinstance(value, dict):
        return value

    restored = {}
    for key, item in value.items():
        restored_key = key
        if isinstance(key, str) and key.startswith('_'):
            restored_key = ''.join(part.capitalize() for part in key[1:].split('_') if part)
        restored[restored_key] = _restore_faktura_payload(item)
    return restored


def _read_setting(settings: dict | None, *keys: str):
    for key in keys:
        value = (settings or {}).get(key)
        if value not in (None, ''):
            return value
    return None


class RestaurantSerializer(serializers.ModelSerializer):
    tariff_id = serializers.PrimaryKeyRelatedField(
        source='tariff',
        queryset=Tariff.objects.filter(is_active=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    restaurant_access_active = serializers.SerializerMethodField()
    permission_codes = serializers.SerializerMethodField()
    role_codes = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()
    starts_on = serializers.SerializerMethodField()
    expires_on = serializers.SerializerMethodField()
    billing_period = serializers.SerializerMethodField()
    activation_type = serializers.SerializerMethodField()
    faktura_payload = serializers.JSONField(required=False)

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'legal_name',
            'tax_number',
            'phone',
            'address',
            'faktura_payload',
            'currency',
            'auth_code',
            'is_active',
            'activated_at',
            'deactivated_at',
            'restaurant_access_active',
            'activation_type',
            'starts_on',
            'expires_on',
            'billing_period',
            'permission_codes',
            'role_codes',
            'tariff',
            'tariff_id',
        )
        extra_kwargs = {'currency': {'required': False}}

    def _get_entitlement(self, instance):
        return getattr(instance, 'entitlement', None)

    def get_restaurant_access_active(self, instance):
        entitlement = self._get_entitlement(instance)
        return bool(entitlement and entitlement.is_active)

    def get_permission_codes(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return []
        return sorted(entitlement.get_effective_permission_codes())

    def get_role_codes(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return []
        return sorted(entitlement.get_effective_role_codes())

    def get_tariff(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None or entitlement.tariff is None:
            return None

        tariff = entitlement.tariff
        return {
            'id': str(tariff.id),
            'name': tariff.name,
            'permission_codes': sorted(entitlement.get_effective_permission_codes()),
            'role_codes': sorted(entitlement.get_effective_role_codes()),
        }

    def get_starts_on(self, instance):
        entitlement = self._get_entitlement(instance)
        return entitlement.starts_on if entitlement is not None else None

    def get_expires_on(self, instance):
        entitlement = self._get_entitlement(instance)
        return entitlement.expires_on if entitlement is not None else None

    def get_billing_period(self, instance):
        entitlement = self._get_entitlement(instance)
        return entitlement.billing_period if entitlement is not None else None

    def get_activation_type(self, instance):
        entitlement = self._get_entitlement(instance)
        if entitlement is None:
            return None
        return 'custom' if entitlement.is_custom else 'tariff'

    def _sync_entitlement(self, restaurant, tariff=serializers.empty):
        if tariff is serializers.empty:
            return

        entitlement, _ = RestaurantEntitlement.objects.get_or_create(restaurant=restaurant)
        entitlement.tariff = tariff
        entitlement.is_custom = False
        entitlement.monthly_price = tariff.monthly_price if tariff is not None else None
        entitlement.yearly_price = tariff.yearly_price if tariff is not None else None
        entitlement.save(update_fields=['tariff', 'is_custom', 'monthly_price', 'yearly_price', 'updated_at'])
        entitlement.permissions.clear()
        entitlement.allowed_roles.clear()

    def create(self, validated_data):
        tariff = validated_data.pop('tariff', serializers.empty)
        faktura_payload = _restore_faktura_payload(validated_data.pop('faktura_payload', {}))
        validated_data['currency'] = 'UZS'
        restaurant = super().create({**validated_data, 'faktura_payload': faktura_payload})
        self._sync_entitlement(restaurant, tariff)
        return restaurant

    def update(self, instance, validated_data):
        tariff = validated_data.pop('tariff', serializers.empty)
        faktura_payload = validated_data.pop('faktura_payload', serializers.empty)
        if faktura_payload is not serializers.empty:
            validated_data['faktura_payload'] = _restore_faktura_payload(faktura_payload)
        validated_data['currency'] = 'UZS'
        restaurant = super().update(instance, validated_data)
        self._sync_entitlement(restaurant, tariff)
        return restaurant


class RestaurantLookupSerializer(serializers.Serializer):
    tax_number = serializers.CharField(source='taxNumber')
    name = serializers.CharField()
    legal_name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    faktura_payload = serializers.JSONField()


class RestaurantActiveUserRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField(allow_blank=True, allow_null=True)
    name = serializers.CharField()


class RestaurantActiveUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'full_name', 'username', 'role')

    def get_role(self, instance):
        if instance.role is None:
            return None
        return RestaurantActiveUserRoleSerializer(instance.role).data


class RestaurantSoliqIntegrationSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    is_enabled = serializers.BooleanField()
    mode = serializers.CharField()
    provider = serializers.CharField()
    terminal_id = serializers.CharField(allow_null=True)
    cashbox_id = serializers.CharField(allow_null=True)
    tax_number = serializers.CharField(allow_null=True)
    endpoint_url = serializers.CharField(allow_null=True)


class RestaurantBalanceSummarySerializer(serializers.Serializer):
    current_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    next_charge_amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    next_charge_on = serializers.DateField(allow_null=True)
    next_period_status = serializers.ChoiceField(choices=('active', 'inactive'), allow_null=True)
    last_top_up_at = serializers.DateTimeField(allow_null=True)


class RestaurantDetailSerializer(RestaurantSerializer):
    active_users = serializers.SerializerMethodField()
    soliq_integration = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta(RestaurantSerializer.Meta):
        fields = RestaurantSerializer.Meta.fields + (
            'active_users',
            'soliq_integration',
            'balance',
        )

    def get_active_users(self, instance):
        active_users = (
            User.objects.filter(restaurant_profile__restaurant=instance, is_active=True)
            .select_related('role', 'employee_profile')
            .exclude(employee_profile__employment_status__in=(
                EmployeeProfile.EmploymentStatus.INACTIVE,
                EmployeeProfile.EmploymentStatus.ARCHIVED,
            ))
            .order_by('full_name', 'username')
            .distinct()
        )
        return RestaurantActiveUserSerializer(active_users, many=True).data

    def get_soliq_integration(self, instance):
        config = (
            IntegrationConfig.objects.filter(
                restaurant=instance,
                kind=IntegrationConfig.Kind.FISCAL,
                provider__in=('soliq-ofd', 'fiscal-drive-service'),
            )
            .order_by('-created_at')
            .first()
        )
        if config is None:
            return None

        payload = {
            'configured': True,
            'is_enabled': config.is_enabled,
            'mode': config.mode,
            'provider': config.provider,
            'terminal_id': _read_setting(config.settings, 'terminal_id', 'terminalId'),
            'cashbox_id': _read_setting(config.settings, 'cashbox_id', 'cashboxId'),
            'tax_number': _read_setting(config.settings, 'tax_number', 'taxNumber'),
            'endpoint_url': _read_setting(config.settings, 'endpoint_url', 'endpointUrl'),
        }
        return RestaurantSoliqIntegrationSerializer(payload).data

    def get_balance(self, instance):
        return RestaurantBalanceSummarySerializer(get_restaurant_balance_summary(instance)).data
