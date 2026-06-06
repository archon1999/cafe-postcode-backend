from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


class IntegrationConfigSerializer(serializers.ModelSerializer):
    def validate_settings(self, value):
        settings = dict(value or {})
        provider = self.initial_data.get('provider') or getattr(self.instance, 'provider', None)
        kind = self.initial_data.get('kind') or getattr(self.instance, 'kind', None)
        connection_type = (settings.get('connection_type') or settings.get('connectionType') or '').strip()

        if kind == IntegrationConfig.Kind.PRINTER and provider == 'windows-raw':
            if connection_type == 'socket':
                settings.pop('transport', None)
                settings.pop('transportType', None)
                settings.pop('use_local_agent', None)
                settings.pop('useLocalAgent', None)
                settings.setdefault('encoding', 'cp1251')
                settings.setdefault('code_page', 46)
            else:
                settings['transport'] = 'local-agent'
                settings.setdefault('encoding', 'cp1251')
                settings.setdefault('code_page', 46)

        return settings

    class Meta:
        model = IntegrationConfig
        fields = ('id', 'kind', 'provider', 'is_enabled', 'settings')
