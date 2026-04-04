from rest_framework import serializers

from apps.accounts.models import Permission, Role
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


class TariffReadMixin:
    def get_permissions(self, obj):
        return list(obj.permissions.values('id', 'code', 'name'))

    def get_allowed_roles(self, obj):
        return list(obj.allowed_roles.values('id', 'code', 'name'))


class TariffSerializer(TariffReadMixin, serializers.ModelSerializer):
    allowed_role_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_roles',
        queryset=Role.objects.filter(is_system=True),
        many=True,
        required=False,
        write_only=True,
    )
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.all(),
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
            'description',
            'monthly_price',
            'yearly_price',
            'is_active',
            'allowed_role_ids',
            'permission_ids',
            'permissions',
            'allowed_roles',
        )

    @staticmethod
    def _derive_permissions(allowed_roles):
        permission_map: dict[str, Permission] = {}
        for role in allowed_roles:
            for permission in role.permissions.all():
                permission_map[str(permission.id)] = permission
        return list(permission_map.values())

    def create(self, validated_data):
        allowed_roles = list(validated_data.pop('allowed_roles', []))
        permissions = validated_data.pop('permissions', serializers.empty)
        tariff = Tariff.objects.create(**validated_data)
        tariff.allowed_roles.set(allowed_roles)
        tariff.permissions.set(
            list(permissions) if permissions is not serializers.empty else self._derive_permissions(allowed_roles)
        )
        return tariff

    def update(self, instance, validated_data):
        allowed_roles = validated_data.pop('allowed_roles', serializers.empty)
        permissions = validated_data.pop('permissions', serializers.empty)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        final_allowed_roles = list(allowed_roles) if allowed_roles is not serializers.empty else list(instance.allowed_roles.all())
        if allowed_roles is not serializers.empty:
            instance.allowed_roles.set(final_allowed_roles)

        if permissions is not serializers.empty:
            instance.permissions.set(list(permissions))
        elif allowed_roles is not serializers.empty:
            instance.permissions.set(self._derive_permissions(final_allowed_roles))
        return instance


class TariffOptionSerializer(TariffReadMixin, serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    allowed_roles = serializers.SerializerMethodField()

    class Meta:
        model = Tariff
        fields = (
            'id',
            'name',
            'description',
            'monthly_price',
            'yearly_price',
            'permissions',
            'allowed_roles',
        )


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
            'permission_ids',
            'allowed_role_ids',
        )


class PartnerActivationResultSerializer(serializers.Serializer):
    partner = BusinessPartnerSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()


class RestaurantActivationSerializer(serializers.Serializer):
    tariff_id = serializers.PrimaryKeyRelatedField(
        source='tariff',
        queryset=Tariff.objects.filter(is_active=True),
    )
    starts_on = serializers.DateField()


class RestaurantActivationResultSerializer(serializers.Serializer):
    restaurant = RestaurantSerializer(read_only=True)
    username = serializers.CharField()
    password = serializers.CharField()
