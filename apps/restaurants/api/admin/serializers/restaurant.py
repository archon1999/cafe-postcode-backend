from rest_framework import serializers

from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
Tariff = get_tariff_model()


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
            'restaurant_access_active',
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
        validated_data['currency'] = 'UZS'
        restaurant = super().create(validated_data)
        self._sync_entitlement(restaurant, tariff)
        return restaurant

    def update(self, instance, validated_data):
        tariff = validated_data.pop('tariff', serializers.empty)
        validated_data['currency'] = 'UZS'
        restaurant = super().update(instance, validated_data)
        self._sync_entitlement(restaurant, tariff)
        return restaurant
