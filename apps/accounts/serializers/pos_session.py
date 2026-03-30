from rest_framework import serializers

from apps.accounts.serializers.auth_session import AuthSessionSerializer
from apps.organizations.models import FeatureConfig
from apps.organizations.serializers import FeatureConfigSerializer

from .pos_restaurant_code import PosRestaurantContextSerializer


class PosSessionUserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    role = serializers.SerializerMethodField()

    def get_role(self, obj):
        if getattr(obj, 'role_id', None) is None:
            return None
        return {
            'id': str(obj.role_id),
            'name': obj.role.name,
        }


class PosSessionSerializer(serializers.Serializer):
    token = serializers.CharField(required=False, allow_blank=True)
    user = PosSessionUserSerializer(read_only=True)
    session = AuthSessionSerializer(read_only=True)
    restaurant_access_active = serializers.SerializerMethodField()
    feature_config = serializers.SerializerMethodField()
    restaurant_context = serializers.SerializerMethodField()

    def get_restaurant_access_active(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return False
        return user.restaurant_access_active

    def get_feature_config(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        restaurant = obj.get('restaurant') if isinstance(obj, dict) else None
        if restaurant is None and user:
            restaurant = user.get_restaurant_scope()
        if not user or restaurant is None:
            return None

        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        data = FeatureConfigSerializer(feature_config).data
        entitlement = getattr(restaurant, 'entitlement', None)
        if entitlement is None:
            return data

        settings = {**(data or {}), **(entitlement.operational_settings or {})}
        settings['restaurant_access_active'] = bool(entitlement.is_active)
        settings['allowed_role_codes'] = sorted(entitlement.get_effective_role_codes())
        settings['allowed_permission_codes'] = sorted(entitlement.get_effective_permission_codes())
        return settings

    def get_restaurant_context(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        restaurant = obj.get('restaurant') if isinstance(obj, dict) else None
        if restaurant is None and user:
            restaurant = user.get_restaurant_scope()
        if restaurant is None:
            return None
        return PosRestaurantContextSerializer(restaurant).data
