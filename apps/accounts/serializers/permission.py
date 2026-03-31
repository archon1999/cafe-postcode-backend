from rest_framework import serializers

from apps.accounts.models import Permission, PermissionEndpoint


class PermissionEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissionEndpoint
        fields = ('method', 'url')


class PermissionSerializer(serializers.ModelSerializer):
    endpoints = PermissionEndpointSerializer(many=True, read_only=True)

    class Meta:
        model = Permission
        fields = (
            'id',
            'code',
            'name',
            'description',
            'surface',
            'resource',
            'action',
            'ui_visible',
            'group_key',
            'endpoints',
        )
