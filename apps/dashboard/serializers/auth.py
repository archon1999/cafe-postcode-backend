from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User


class OwnerDashboardRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class OwnerDashboardUserSerializer(serializers.ModelSerializer):
    role = OwnerDashboardRoleSerializer(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    restaurant_id = serializers.SerializerMethodField()
    restaurant_name = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)

    def get_restaurant_id(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'id', None)

    def get_restaurant_name(self, instance):
        restaurant = instance.get_restaurant_scope()
        return getattr(restaurant, 'name', None)

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'full_name',
            'is_superuser',
            'restaurant_id',
            'restaurant_name',
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
