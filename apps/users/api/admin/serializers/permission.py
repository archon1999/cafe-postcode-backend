from rest_framework import serializers

from apps.users.helpers import get_permission_model

Permission = get_permission_model()


class PermissionSerializer(serializers.ModelSerializer):
    scope = serializers.SerializerMethodField()
    endpoints = serializers.SerializerMethodField()

    def get_scope(self, instance):
        return instance.surface

    def get_endpoints(self, instance):
        return [
            {'method': endpoint.method, 'url': endpoint.url}
            for endpoint in instance.endpoints.all()
        ]

    class Meta:
        model = Permission
        fields = ('id', 'code', 'scope', 'name', 'description', 'endpoints')


class PermissionOptionSerializer(serializers.ModelSerializer):
    scope = serializers.SerializerMethodField()

    def get_scope(self, instance):
        return instance.surface

    class Meta:
        model = Permission
        fields = ('id', 'code', 'scope', 'name', 'description')
