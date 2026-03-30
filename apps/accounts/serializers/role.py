from rest_framework import serializers

from apps.accounts.models import Role

from .permission import PermissionSerializer


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ('id', 'code', 'name', 'description', 'permissions')
