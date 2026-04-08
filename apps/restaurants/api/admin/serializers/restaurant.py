from rest_framework import serializers

from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
Tariff = get_tariff_model()


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
