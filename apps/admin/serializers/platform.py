from rest_framework import serializers

from apps.accounts.models import Permission, Role, User
from apps.admin.serializers.constructor import RestaurantSerializer
from apps.organizations.models import BusinessPartner, RestaurantEntitlement, Tariff


def _restore_faktura_payload(value):
    if isinstance(value, list):
        return [_restore_faktura_payload(item) for item in value]

    if not isinstance(value, dict):
        return value

    restored = {}
    for key, item in value.items():
        restored_key = key
        if isinstance(key, str) and key.startswith('_'):
            restored_key = ''.join(part.capitalize() for part in key[1:].split('_') if part)
        restored[restored_key] = _restore_faktura_payload(item)
    return restored


class BusinessPartnerSerializer(serializers.ModelSerializer):
    owner_user_id = serializers.UUIDField(read_only=True)
    faktura_payload = serializers.JSONField(required=False)

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

    def create(self, validated_data):
        faktura_payload = _restore_faktura_payload(validated_data.pop('faktura_payload', {}))
        return BusinessPartner.objects.create(faktura_payload=faktura_payload, **validated_data)

    def update(self, instance, validated_data):
        faktura_payload = validated_data.pop('faktura_payload', serializers.empty)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if faktura_payload is not serializers.empty:
            instance.faktura_payload = _restore_faktura_payload(faktura_payload)

        instance.save()
        return instance


class BusinessPartnerLookupSerializer(serializers.Serializer):
    inn = serializers.CharField()
    company_name = serializers.CharField(source='companyName')
    legal_name = serializers.CharField(source='legalName')
    director_name = serializers.CharField(source='directorName', allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    faktura_payload = serializers.JSONField()


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

    @staticmethod
    def _merge_permissions_with_allowed_roles(*, permissions, allowed_roles):
        permission_map = {}
        for permission in permissions or []:
            permission_map[permission.id] = permission
        for role in allowed_roles or []:
            for permission in role.permissions.all():
                permission_map[permission.id] = permission
        return list(permission_map.values())

    def create(self, validated_data):
        permissions = list(validated_data.pop('permissions', []))
        allowed_roles = list(validated_data.pop('allowed_roles', []))
        tariff = Tariff.objects.create(**validated_data)
        tariff.allowed_roles.set(allowed_roles)
        tariff.permissions.set(
            self._merge_permissions_with_allowed_roles(
                permissions=permissions,
                allowed_roles=allowed_roles,
            )
        )
        return tariff

    def update(self, instance, validated_data):
        permissions = list(validated_data.pop('permissions', instance.permissions.all()))
        allowed_roles = list(validated_data.pop('allowed_roles', instance.allowed_roles.all()))

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        instance.allowed_roles.set(allowed_roles)
        instance.permissions.set(
            self._merge_permissions_with_allowed_roles(
                permissions=permissions,
                allowed_roles=allowed_roles,
            )
        )
        return instance

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
