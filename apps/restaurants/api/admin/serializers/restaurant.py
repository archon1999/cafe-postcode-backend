import json
from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.platform.services import get_restaurant_balance_summary
from apps.restaurants.helpers import get_restaurant_model
from apps.users.helpers import get_employee_profile_model, get_user_model
from common.utils.settings import get_setting

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
    pos_auth_background_image = serializers.ImageField(required=False, allow_null=True, write_only=True)
    pos_auth_background_image_url = serializers.SerializerMethodField()
    clear_pos_auth_background_image = serializers.BooleanField(required=False, default=False, write_only=True)
    service_fee_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('0'),
        max_value=Decimal('99'),
        required=False,
    )

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'legal_name',
            'tax_number',
            'phone',
            'social',
            'address',
            'faktura_payload',
            'currency',
            'auth_code',
            'service_fee_enabled',
            'service_fee_percent',
            'vat_enabled',
            'vat_percent',
            'marking_check_enabled',
            'pos_auth_background_image',
            'pos_auth_background_image_url',
            'clear_pos_auth_background_image',
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

    def get_pos_auth_background_image_url(self, instance):
        image = getattr(instance, 'pos_auth_background_image', None)
        if image and getattr(image, 'name', ''):
            return image.url
        return None

    def validate_faktura_payload(self, value):
        if isinstance(value, str):
            if not value.strip():
                return {}
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError('Faktura payload must be valid JSON.') from exc
            if not isinstance(parsed_value, dict):
                raise serializers.ValidationError('Faktura payload must be an object.')
            return parsed_value
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        clear_image = attrs.get('clear_pos_auth_background_image', False)
        image = attrs.get('pos_auth_background_image')

        if clear_image and image is not None:
            raise serializers.ValidationError(
                {'pos_auth_background_image': 'Image upload cannot be combined with image removal.'}
            )

        if clear_image:
            attrs['pos_auth_background_image'] = None

        return attrs

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
        validated_data.pop('clear_pos_auth_background_image', False)
        faktura_payload = _restore_faktura_payload(validated_data.pop('faktura_payload', {}))
        validated_data['currency'] = 'UZS'
        restaurant = super().create({**validated_data, 'faktura_payload': faktura_payload})
        self._sync_entitlement(restaurant, tariff)
        return restaurant

    def update(self, instance, validated_data):
        tariff = validated_data.pop('tariff', serializers.empty)
        validated_data.pop('clear_pos_auth_background_image', False)
        faktura_payload = validated_data.pop('faktura_payload', serializers.empty)
        if faktura_payload is not serializers.empty:
            validated_data['faktura_payload'] = _restore_faktura_payload(faktura_payload)
        validated_data['currency'] = 'UZS'
        old_image = instance.pos_auth_background_image
        old_image_name = old_image.name if old_image and getattr(old_image, 'name', '') else ''
        old_image_storage = old_image.storage if old_image_name else None
        restaurant = super().update(instance, validated_data)
        self._sync_entitlement(restaurant, tariff)
        new_image = restaurant.pos_auth_background_image
        new_image_name = new_image.name if new_image and getattr(new_image, 'name', '') else ''
        if old_image_name and old_image_name != new_image_name and old_image_storage is not None:
            old_image_storage.delete(old_image_name)
        return restaurant


class RestaurantSelfServiceSerializer(serializers.ModelSerializer):
    """Restaurant-owned settings without platform, entitlement, or Faktura write access."""

    PLATFORM_OWNED_INPUT_FIELDS = frozenset(
        {
            'business_partner',
            'business_partner_id',
            'tariff',
            'tariff_id',
            'faktura_payload',
            'auth_code',
            'currency',
            'legal_name',
            'tax_number',
            'is_active',
            'activated_at',
            'deactivated_at',
            'starts_on',
            'expires_on',
            'billing_period',
        }
    )

    restaurant_access_active = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()
    starts_on = serializers.SerializerMethodField()
    expires_on = serializers.SerializerMethodField()
    billing_period = serializers.SerializerMethodField()
    activation_type = serializers.SerializerMethodField()
    pos_auth_background_image = serializers.ImageField(required=False, allow_null=True, write_only=True)
    pos_auth_background_image_url = serializers.SerializerMethodField()
    clear_pos_auth_background_image = serializers.BooleanField(required=False, default=False, write_only=True)
    service_fee_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('0'),
        max_value=Decimal('99'),
        required=False,
    )

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'legal_name',
            'tax_number',
            'phone',
            'social',
            'address',
            'currency',
            'auth_code',
            'service_fee_enabled',
            'service_fee_percent',
            'vat_enabled',
            'vat_percent',
            'marking_check_enabled',
            'pos_auth_background_image',
            'pos_auth_background_image_url',
            'clear_pos_auth_background_image',
            'is_active',
            'activated_at',
            'deactivated_at',
            'restaurant_access_active',
            'activation_type',
            'starts_on',
            'expires_on',
            'billing_period',
            'tariff',
        )
        read_only_fields = (
            'id',
            'legal_name',
            'tax_number',
            'currency',
            'auth_code',
            'is_active',
            'activated_at',
            'deactivated_at',
        )

    @staticmethod
    def _entitlement(instance):
        return getattr(instance, 'entitlement', None)

    def get_restaurant_access_active(self, instance):
        entitlement = self._entitlement(instance)
        return bool(entitlement and entitlement.is_active)

    def get_tariff(self, instance):
        entitlement = self._entitlement(instance)
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
        entitlement = self._entitlement(instance)
        return entitlement.starts_on if entitlement is not None else None

    def get_expires_on(self, instance):
        entitlement = self._entitlement(instance)
        return entitlement.expires_on if entitlement is not None else None

    def get_billing_period(self, instance):
        entitlement = self._entitlement(instance)
        return entitlement.billing_period if entitlement is not None else None

    def get_activation_type(self, instance):
        entitlement = self._entitlement(instance)
        if entitlement is None:
            return None
        return 'custom' if entitlement.is_custom else 'tariff'

    def get_pos_auth_background_image_url(self, instance):
        image = getattr(instance, 'pos_auth_background_image', None)
        if image and getattr(image, 'name', ''):
            return image.url
        return None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        clear_image = attrs.get('clear_pos_auth_background_image', False)
        image = attrs.get('pos_auth_background_image')
        if clear_image and image is not None:
            raise serializers.ValidationError(
                {'pos_auth_background_image': 'Image upload cannot be combined with image removal.'}
            )
        if clear_image:
            attrs['pos_auth_background_image'] = None
        return attrs

    def to_internal_value(self, data):
        forbidden = sorted(self.PLATFORM_OWNED_INPUT_FIELDS.intersection(data.keys()))
        if forbidden:
            raise serializers.ValidationError(
                {field: 'This field is managed by the platform and cannot be changed here.' for field in forbidden}
            )
        return super().to_internal_value(data)

    def update(self, instance, validated_data):
        validated_data.pop('clear_pos_auth_background_image', False)
        old_image = instance.pos_auth_background_image
        old_image_name = old_image.name if old_image and getattr(old_image, 'name', '') else ''
        old_image_storage = old_image.storage if old_image_name else None
        restaurant = super().update(instance, validated_data)
        new_image = restaurant.pos_auth_background_image
        new_image_name = new_image.name if new_image and getattr(new_image, 'name', '') else ''
        if old_image_name and old_image_name != new_image_name and old_image_storage is not None:
            old_image_storage.delete(old_image_name)
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
            )
            .order_by('-is_enabled', 'provider', '-created_at')
            .first()
        )
        if config is None:
            return None

        payload = {
            'configured': True,
            'is_enabled': config.is_enabled,
            'provider': config.provider,
            'terminal_id': get_setting(config.settings, 'terminal_id', 'terminalId'),
            'cashbox_id': get_setting(config.settings, 'cashbox_id', 'cashboxId'),
            'tax_number': get_setting(config.settings, 'tax_number', 'taxNumber'),
            'endpoint_url': get_setting(config.settings, 'endpoint_url', 'endpointUrl'),
        }
        return RestaurantSoliqIntegrationSerializer(payload).data

    def get_balance(self, instance):
        return RestaurantBalanceSummarySerializer(get_restaurant_balance_summary(instance)).data
