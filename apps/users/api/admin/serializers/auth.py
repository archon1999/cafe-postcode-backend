from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .role import RoleSerializer

User = get_user_model()


def get_business_partner_model():
    return apps.get_model('platform', 'BusinessPartner')


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


class MFAChallengeTokenSerializer(serializers.Serializer):
    challenge_token = serializers.CharField(min_length=32, max_length=512, trim_whitespace=True)


class MFACodeSerializer(MFAChallengeTokenSerializer):
    code = serializers.CharField(required=False, allow_blank=True, max_length=16, trim_whitespace=True)
    recovery_code = serializers.CharField(required=False, allow_blank=True, max_length=64, trim_whitespace=True)

    def validate(self, attrs):
        if bool(attrs.get('code')) == bool(attrs.get('recovery_code')):
            raise serializers.ValidationError('Provide exactly one TOTP code or recovery code.')
        return attrs


class MFAStepUpSerializer(serializers.Serializer):
    code = serializers.CharField(required=False, allow_blank=True, max_length=16, trim_whitespace=True)
    recovery_code = serializers.CharField(required=False, allow_blank=True, max_length=64, trim_whitespace=True)

    def validate(self, attrs):
        if bool(attrs.get('code')) == bool(attrs.get('recovery_code')):
            raise serializers.ValidationError('Provide exactly one TOTP code or recovery code.')
        return attrs


class AdminUnlockSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=1, max_length=256, trim_whitespace=False)


class SessionUserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    permission_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    restaurant_access_active = serializers.BooleanField(read_only=True)
    restaurant_id = serializers.SerializerMethodField()
    business_partner_id = serializers.SerializerMethodField()
    business_partners_count = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    inn = serializers.SerializerMethodField()
    restaurant_name = serializers.SerializerMethodField()
    activated_at = serializers.SerializerMethodField()
    activation_type = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()

    def get_restaurant_id(self, obj):
        restaurant = obj.get_restaurant_scope()
        return str(restaurant.id) if restaurant is not None else None

    def get_business_partner_id(self, obj):
        business_partner = obj.get_business_partner_scope()
        return str(business_partner.id) if business_partner is not None else None

    def get_business_partners_count(self, obj):
        if obj.is_superuser or obj.get_restaurant_scope() is not None or obj.get_business_partner_scope() is not None:
            return None
        return get_business_partner_model().objects.count()

    def get_company_name(self, obj):
        business_partner = obj.get_business_partner_scope()
        return business_partner.company_name if business_partner is not None else None

    def get_inn(self, obj):
        business_partner = obj.get_business_partner_scope()
        return business_partner.inn if business_partner is not None else None

    def get_restaurant_name(self, obj):
        restaurant = obj.get_restaurant_scope()
        return restaurant.name if restaurant is not None else None

    def _get_entitlement(self, obj):
        restaurant = obj.get_restaurant_scope()
        if restaurant is None:
            return None
        return getattr(restaurant, 'entitlement', None)

    def get_activated_at(self, obj):
        restaurant = obj.get_restaurant_scope()
        return getattr(restaurant, 'activated_at', None) if restaurant is not None else None

    def get_activation_type(self, obj):
        entitlement = self._get_entitlement(obj)
        if entitlement is None:
            return None
        return 'custom' if entitlement.is_custom else 'tariff'

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
            'business_partners_count',
            'company_name',
            'inn',
            'restaurant_name',
            'activated_at',
            'activation_type',
            'tariff',
        )
