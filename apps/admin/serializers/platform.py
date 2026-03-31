from rest_framework import serializers

from apps.accounts.models import Permission, Role, User
from apps.admin.serializers.constructor import RestaurantSerializer
from apps.organizations.models import BusinessPartner, RestaurantEntitlement, Tariff


class BusinessPartnerSerializer(serializers.ModelSerializer):
    owner_user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = BusinessPartner
        fields = (
            'id',
            'inn',
            'company_name',
            'legal_name',
            'director_name',
            'phone',
            'email',
            'address',
            'status',
            'owner_user_id',
            'activated_at',
            'deactivated_at',
            'faktura_payload',
        )


class TariffSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )
    allowed_role_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_roles',
        queryset=Role.objects.filter(is_system=True),
        many=True,
        required=False,
        write_only=True,
    )
    permissions = serializers.SerializerMethodField()
    allowed_roles = serializers.SerializerMethodField()

    class Meta:
        model = Tariff
        fields = (
            'id',
            'name',
            'classification',
            'description',
            'monthly_price',
            'yearly_price',
            'is_active',
            'operational_settings',
            'permission_ids',
            'allowed_role_ids',
            'permissions',
            'allowed_roles',
        )

    def get_permissions(self, obj):
        return list(obj.permissions.values('id', 'code', 'name'))

    def get_allowed_roles(self, obj):
        return list(obj.allowed_roles.values('id', 'code', 'name'))


class RestaurantEntitlementSerializer(serializers.ModelSerializer):
    tariff_name = serializers.CharField(source='tariff.name', read_only=True)
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )
    allowed_role_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_roles',
        queryset=Role.objects.filter(is_system=True),
        many=True,
        required=False,
        write_only=True,
    )

    class Meta:
        model = RestaurantEntitlement
        fields = (
            'id',
            'restaurant',
            'tariff',
            'tariff_name',
            'is_custom',
            'is_active',
            'starts_on',
            'monthly_price',
            'yearly_price',
            'operational_settings',
            'permission_ids',
            'allowed_role_ids',
        )


class PartnerActivationResultSerializer(serializers.Serializer):
    partner = BusinessPartnerSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()


class RestaurantActivationSerializer(serializers.Serializer):
    tariff_id = serializers.PrimaryKeyRelatedField(source='tariff', queryset=Tariff.objects.filter(is_active=True), required=False, allow_null=True)
    custom_tariff = serializers.BooleanField(required=False, default=False)
    monthly_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    yearly_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    starts_on = serializers.DateField()
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.all(),
        many=True,
        required=False,
    )
    allowed_role_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_roles',
        queryset=Role.objects.filter(is_system=True),
        many=True,
        required=False,
    )
    operational_settings = serializers.JSONField(required=False)

    def validate(self, attrs):
        if not attrs.get('custom_tariff') and not attrs.get('tariff'):
            raise serializers.ValidationError({'tariffId': 'Tariff is required unless custom tariff is enabled.'})
        return attrs


class RestaurantActivationResultSerializer(serializers.Serializer):
    restaurant = RestaurantSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()
