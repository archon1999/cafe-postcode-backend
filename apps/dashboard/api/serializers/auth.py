from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.dashboard.services import get_dashboard_accessible_restaurants

User = get_user_model()


class OwnerDashboardRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class OwnerDashboardUserSerializer(serializers.ModelSerializer):
    role = OwnerDashboardRoleSerializer(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    restaurant_id = serializers.SerializerMethodField()
    restaurant_name = serializers.SerializerMethodField()
    restaurant_options = serializers.SerializerMethodField()
    can_view_all_restaurants = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)

    def get_restaurant_id(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'id', None)

    def get_restaurant_name(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'name', None)

    def get_restaurant_options(self, instance):
        return [
            {
                'id': restaurant.id,
                'name': restaurant.name,
                'is_parent': restaurant.parent_restaurant_id is None,
            }
            for restaurant in get_dashboard_accessible_restaurants(instance)
        ]

    def get_can_view_all_restaurants(self, instance):
        return get_dashboard_accessible_restaurants(instance).count() > 1

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'full_name',
            'is_superuser',
            'restaurant_id',
            'restaurant_name',
            'restaurant_options',
            'can_view_all_restaurants',
            'role',
            'permission_codes',
        )


class OwnerDashboardLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user or not user.is_active:
            raise serializers.ValidationError(_('Invalid credentials.'))

        if user.is_superuser:
            attrs['user'] = user
            return attrs

        if 'dashboard.view' not in set(user.permission_codes):
            raise serializers.ValidationError(_('Only users with dashboard access can open the owner dashboard.'))

        attrs['user'] = user
        return attrs
