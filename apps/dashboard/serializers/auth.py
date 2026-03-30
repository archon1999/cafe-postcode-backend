from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User


class OwnerDashboardRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()


class OwnerDashboardUserSerializer(serializers.ModelSerializer):
    role = OwnerDashboardRoleSerializer(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    restaurant_id = serializers.UUIDField(read_only=True)
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)
    branch_id = serializers.UUIDField(read_only=True, allow_null=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, allow_null=True)
    is_superuser = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'full_name',
            'ui_mode',
            'is_superuser',
            'restaurant_id',
            'restaurant_name',
            'branch_id',
            'branch_name',
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

        if user.ui_mode != User.UiMode.ADMIN:
            raise serializers.ValidationError(_('User is not allowed in owner dashboard.'))

        if not user.role_id or user.role.code != 'owner':
            raise serializers.ValidationError(_('Only owner accounts can access the owner dashboard.'))

        attrs['user'] = user
        return attrs
