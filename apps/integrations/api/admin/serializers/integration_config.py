from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


class IntegrationConfigSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, obj):
        settings = obj.settings or {}
        if obj.kind == IntegrationConfig.Kind.PRINTER:
            printer_name = settings.get('printer_name') or settings.get('printerName')
            host = settings.get('host')
            port = settings.get('port')
            connection_type = settings.get('connection_type') or settings.get('connectionType')

            if host:
                endpoint = f'{host}:{port}' if port else str(host)
                return f'{obj.provider} (LAN TCP/IP: {endpoint})'

            if printer_name:
                return f'{obj.provider} (Windows/USB: {printer_name})'

            if connection_type:
                return f'{obj.provider} ({connection_type})'

        terminal_id = settings.get('terminal_id') or settings.get('terminalId') or settings.get('fiscal')
        endpoint_url = settings.get('endpoint_url') or settings.get('endpointUrl')
        suffix = terminal_id or endpoint_url
        if suffix:
            return f'{obj.provider} ({suffix})'

        return f'{obj.provider} ({str(obj.id)[-6:]})'

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
        fields = ('id', 'kind', 'provider', 'display_name', 'is_enabled', 'settings')
        read_only_fields = ('display_name',)
