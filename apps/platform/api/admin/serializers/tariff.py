from rest_framework import serializers

from apps.platform.helpers import get_tariff_model
from apps.users.helpers import get_permission_model, get_role_model

Tariff = get_tariff_model()
Permission = get_permission_model()
Role = get_role_model()


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

        final_allowed_roles = (
            list(allowed_roles) if allowed_roles is not serializers.empty else list(instance.allowed_roles.all())
        )
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
