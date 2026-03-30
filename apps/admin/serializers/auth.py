from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.admin.serializers.users import RoleSerializer


class AdminLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user or not user.is_active:
            raise serializers.ValidationError(_('Invalid credentials.'))
        if not user.can_access_admin_ui:
            raise serializers.ValidationError(_('User is not allowed in admin UI.'))
        attrs['user'] = user
        return attrs


class SessionUserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    restaurant_access_active = serializers.BooleanField(read_only=True)
    restaurant_id = serializers.SerializerMethodField()
    business_partner_id = serializers.SerializerMethodField()

    def get_restaurant_id(self, obj):
        restaurant = obj.get_restaurant_scope()
        return str(restaurant.id) if restaurant is not None else None

    def get_business_partner_id(self, obj):
        business_partner = obj.get_business_partner_scope()
        return str(business_partner.id) if business_partner is not None else None

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'full_name',
            'phone',
            'is_active',
            'is_superuser',
            'restaurant_access_active',
            'role',
            'business_partner_id',
            'restaurant_id',
            'permission_codes',
        )
