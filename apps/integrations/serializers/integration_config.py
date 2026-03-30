from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


class IntegrationConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationConfig
        fields = ('id', 'branch', 'kind', 'provider', 'mode', 'is_enabled', 'settings')
