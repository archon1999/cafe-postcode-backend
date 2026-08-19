from rest_framework import serializers

from apps.platform.helpers import get_restaurant_entitlement_model, get_tariff_model
from apps.platform.selectors.business_partners import (
    ACTIVATION_EXCLUDED_ROLE_CODES,
    ensure_dashboard_permission_for_admin_roles,
)
from apps.restaurants.api.admin.serializers import RestaurantSerializer
from apps.users.api.admin.serializers import PermissionOptionSerializer, RoleSerializer
from apps.users.helpers import get_permission_model, get_role_model

from .tariff import TariffOptionSerializer

Permission = get_permission_model()
Role = get_role_model()
Tariff = get_tariff_model()
RestaurantEntitlement = get_restaurant_entitlement_model()
CUSTOM_TARIFF_PERMISSION_CODE = 'restaurants.custom_tariff'


class RestaurantActivationSerializer(serializers.Serializer):
    activation_type = serializers.ChoiceField(choices=('tariff', 'custom'), default='tariff')
    tariff_id = serializers.PrimaryKeyRelatedField(
        source='tariff',
        queryset=Tariff.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    allowed_role_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_roles',
        queryset=Role.objects.filter(is_system=True).exclude(code__in=ACTIVATION_EXCLUDED_ROLE_CODES),
        many=True,
        required=False,
    )
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.filter(roles__is_system=True)
        .exclude(roles__code__in=ACTIVATION_EXCLUDED_ROLE_CODES)
        .distinct(),
        many=True,
        required=False,
    )
    @staticmethod
    def _derive_permissions(allowed_roles):
        permission_map: dict[str, Permission] = {}
        for role in allowed_roles:
            for permission in role.permissions.all():
                permission_map[str(permission.id)] = permission
        return list(permission_map.values())

    def validate(self, attrs):
        attrs = super().validate(attrs)

        activation_type = attrs.get('activation_type', 'tariff')
        tariff = attrs.get('tariff')
        allowed_roles = list(attrs.get('allowed_roles', []))
        permissions = list(attrs.get('permissions', []))

        if activation_type == 'tariff':
            if tariff is None:
                raise serializers.ValidationError({'tariffId': 'Tarif tanlang.'})
            return attrs

        request = self.context.get('request')
        if CUSTOM_TARIFF_PERMISSION_CODE not in set(getattr(getattr(request, 'user', None), 'permission_codes', [])):
            raise serializers.ValidationError({'activationType': 'Maxsus tarif uchun ruxsat yo‘q.'})

        if not allowed_roles:
            raise serializers.ValidationError({'allowedRoleIds': 'Kamida bitta rol tanlang.'})

        if not any(role.code in {'restaurant_admin', 'fast_food_admin'} for role in allowed_roles):
            raise serializers.ValidationError({'allowedRoleIds': "Custom tarifda admin roli bo'lishi shart."})

        if not permissions:
            permissions = self._derive_permissions(allowed_roles)

        if not permissions:
            raise serializers.ValidationError({'permissionIds': 'Kamida bitta ruxsat tanlang.'})

        attrs['permissions'] = ensure_dashboard_permission_for_admin_roles(allowed_roles, permissions)
        attrs['tariff'] = None
        return attrs


class RestaurantActivationOptionsSerializer(serializers.Serializer):
    tariffs = TariffOptionSerializer(many=True, read_only=True)
    roles = RoleSerializer(many=True, read_only=True)
    permissions = PermissionOptionSerializer(many=True, read_only=True)
    custom_tariff_allowed = serializers.BooleanField(read_only=True)


class RestaurantActivationResultSerializer(serializers.Serializer):
    restaurant = RestaurantSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()
