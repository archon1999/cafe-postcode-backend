from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


class IntegrationConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationConfig
        fields = ('id', 'kind', 'provider', 'is_enabled', 'settings')
