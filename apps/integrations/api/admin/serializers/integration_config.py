from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


_LOCAL_AGENT_TRANSPORT_ALIASES = (
    "transport_type",
    "transportType",
    "use_local_agent",
    "useLocalAgent",
)


def _normalize_local_agent_transport_settings(settings):
    normalized = dict(settings)
    normalized["transport"] = "local-agent"
    for alias in _LOCAL_AGENT_TRANSPORT_ALIASES:
        normalized.pop(alias, None)
    return normalized


class IntegrationConfigSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True)
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, obj):
        if obj.name:
            return obj.name
        settings = obj.settings or {}
        if obj.kind == IntegrationConfig.Kind.PRINTER:
            printer_name = settings.get("printer_name") or settings.get("printerName")
            host = settings.get("host")
            port = settings.get("port")
            connection_type = settings.get("connection_type") or settings.get(
                "connectionType"
            )

            if host:
                endpoint = f"{host}:{port}" if port else str(host)
                return f"{obj.provider} (LAN TCP/IP: {endpoint})"

            if printer_name:
                return f"{obj.provider} (Windows/USB: {printer_name})"

            if connection_type:
                return f"{obj.provider} ({connection_type})"

        terminal_id = (
            settings.get("factory_id")
            or settings.get("factoryId")
            or settings.get("terminal_id")
            or settings.get("terminalId")
            or settings.get("fiscal")
        )
        endpoint_url = settings.get("endpoint_url") or settings.get("endpointUrl")
        suffix = terminal_id or endpoint_url
        if suffix:
            return f"{obj.provider} ({suffix})"

        return f"{obj.provider} ({str(obj.id)[-6:]})"

    def validate_settings(self, value):
        settings = dict(value or {})
        provider = self.initial_data.get("provider") or getattr(
            self.instance, "provider", None
        )
        kind = self.initial_data.get("kind") or getattr(self.instance, "kind", None)
        connection_type = (
            settings.get("connection_type") or settings.get("connectionType") or ""
        ).strip()

        if kind == IntegrationConfig.Kind.PRINTER and provider == "windows-raw":
            settings = _normalize_local_agent_transport_settings(settings)
            settings.setdefault("encoding", "cp1251")
            settings.setdefault("code_page", 46)

        if kind == IntegrationConfig.Kind.FISCAL and provider == "fiscal-drive-service":
            settings = _normalize_local_agent_transport_settings(settings)

        return settings

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        provider = attrs.get("provider", getattr(self.instance, "provider", None))
        if kind == IntegrationConfig.Kind.FISCAL and provider != "fiscal-drive-service":
            raise serializers.ValidationError(
                {"provider": "Fiscal Drive is the only supported fiscal provider."}
            )
        return attrs

    class Meta:
        model = IntegrationConfig
        fields = (
            "id",
            "restaurant_name",
            "name",
            "kind",
            "provider",
            "display_name",
            "is_enabled",
            "settings",
        )
        read_only_fields = ("restaurant_name", "display_name")
