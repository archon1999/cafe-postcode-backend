from rest_framework import serializers

from apps.users.api.admin.serializers import AuthSessionSerializer

from .restaurant import PosRestaurantContextSerializer


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
    role_codes = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()
    restaurant_context = serializers.SerializerMethodField()

    def get_restaurant_access_active(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        if not user:
            return False
        return user.restaurant_access_active

    def _get_restaurant(self, obj):
        user = obj.get('user') if isinstance(obj, dict) else getattr(obj, 'user', None)
        restaurant = obj.get('restaurant') if isinstance(obj, dict) else None
        if restaurant is None and user:
            restaurant = user.get_restaurant_scope()
        return restaurant

    def _get_entitlement(self, obj):
        restaurant = self._get_restaurant(obj)
        if restaurant is None:
            return None
        return getattr(restaurant, 'entitlement', None)

    def get_role_codes(self, obj):
        entitlement = self._get_entitlement(obj)
        if entitlement is None:
            return []
        return sorted(entitlement.get_effective_role_codes())

    def get_tariff(self, obj):
        entitlement = self._get_entitlement(obj)
        if entitlement is None or entitlement.tariff is None:
            return None

        tariff = entitlement.tariff
        return {
            'id': str(tariff.id),
            'name': tariff.name,
            'permission_codes': sorted(entitlement.get_effective_permission_codes()),
            'role_codes': sorted(entitlement.get_effective_role_codes()),
        }

    def get_restaurant_context(self, obj):
        restaurant = self._get_restaurant(obj)
        if restaurant is None:
            return None
        return PosRestaurantContextSerializer(restaurant).data
