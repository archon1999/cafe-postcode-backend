from django.utils.text import slugify
from rest_framework import serializers

from apps.users.helpers import get_permission_model, get_role_model

from .permission import PermissionSerializer

Permission = get_permission_model()
Role = get_role_model()


class RoleSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ('id', 'code', 'name', 'description', 'is_system', 'permissions', 'permission_ids')
        read_only_fields = ('code', 'is_system')

    def _generate_internal_code(self, name: str, instance: Role | None = None) -> str:
        base_code = slugify(name).replace('-', '_') or 'role'
        code = base_code
        suffix = 2

        queryset = Role.objects.all()
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)

        while queryset.filter(code=code).exists():
            code = f'{base_code}_{suffix}'
            suffix += 1

        return code

    def create(self, validated_data):
        validated_data['code'] = self._generate_internal_code(validated_data.get('name', 'role'))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'name' in validated_data and validated_data['name'] != instance.name:
            validated_data['code'] = self._generate_internal_code(validated_data['name'], instance=instance)
        return super().update(instance, validated_data)
