from urllib.parse import urlsplit

from rest_framework import serializers

from apps.integrations.models import IntegrationConfig


_LOCAL_AGENT_TRANSPORT_ALIASES = (
    "transport_type",
    "transportType",
    "use_local_agent",
    "useLocalAgent",
)
_MASK = "********"
_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "credential",
)
_ENDPOINT_KEYS = frozenset({"endpoint_url", "endpointurl", "service_url", "serviceurl"})


def _normalized_key(value):
    return "".join(character.lower() if character.isalnum() else "_" for character in str(value))


def _is_secret_key(key):
    normalized = _normalized_key(key)
    compact = normalized.replace("_", "")
    return any(part in normalized or part.replace("_", "") in compact for part in _SECRET_KEY_PARTS)


def _endpoint_has_sensitive_components(value):
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
        # Accessing port also rejects malformed bracketed hosts and ports.
        _ = parsed.port
    except ValueError:
        return True
    return (
        parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or any(character in raw for character in ("\r", "\n", "\x00"))
    )


def _mask_settings(value):
    if isinstance(value, dict):
        return {
            key: (
                _MASK
                if (
                    (_is_secret_key(key) and item not in (None, ""))
                    or (
                        _normalized_key(key) in _ENDPOINT_KEYS
                        and _endpoint_has_sensitive_components(item)
                    )
                )
                else _mask_settings(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_settings(item) for item in value]
    return value


def _restore_masked_secrets(incoming, existing, *, path=()):
    if isinstance(incoming, dict):
        existing_values = existing if isinstance(existing, dict) else {}
        return {
            key: _restore_masked_secrets(value, existing_values.get(key), path=(*path, key))
            for key, value in incoming.items()
        }
    if isinstance(incoming, list):
        existing_values = existing if isinstance(existing, list) else []
        return [
            _restore_masked_secrets(
                value,
                existing_values[index] if index < len(existing_values) else None,
                path=(*path, str(index)),
            )
            for index, value in enumerate(incoming)
        ]
    if incoming == _MASK and path and _is_secret_key(path[-1]):
        if existing is None:
            raise serializers.ValidationError("Masked secret has no existing value to preserve.")
        return existing
    return incoming


def _preserve_omitted_secrets(incoming, existing):
    if not isinstance(incoming, dict) or not isinstance(existing, dict):
        return incoming
    result = dict(incoming)
    for key, existing_value in existing.items():
        if key not in result:
            if _is_secret_key(key):
                result[key] = existing_value
            continue
        if isinstance(result[key], dict) and isinstance(existing_value, dict):
            result[key] = _preserve_omitted_secrets(result[key], existing_value)
    return result


def _normalize_local_agent_transport_settings(settings):
    normalized = dict(settings)
    normalized["transport"] = "local-agent"
    for alias in _LOCAL_AGENT_TRANSPORT_ALIASES:
        normalized.pop(alias, None)
    return normalized


def _validate_endpoint_components(settings):
    for key, value in settings.items():
        if _normalized_key(key) not in _ENDPOINT_KEYS or value in (None, ""):
            continue
        if _endpoint_has_sensitive_components(value):
            raise serializers.ValidationError(
                {
                    key: (
                        "Integration endpoints must not contain credentials, query parameters, "
                        "fragments, control characters, or malformed ports. Store credentials in "
                        "a dedicated secret setting instead."
                    )
                }
            )


def _validate_printer_target(settings):
    host = str(settings.get("host") or "").strip()
    connection_type = str(
        settings.get("connection_type")
        or settings.get("connectionType")
        or ("socket" if host else "system_printer")
    ).strip().lower()
    if connection_type == "socket":
        try:
            port = int(settings.get("port") or 9100)
        except (TypeError, ValueError) as error:
            raise serializers.ValidationError({"port": "Socket printer port must be 9100."}) from error
        if not host:
            raise serializers.ValidationError({"host": "Socket printer host is required."})
        if port != 9100:
            raise serializers.ValidationError({"port": "Socket printer port must be 9100."})
        return
    if connection_type != "system_printer":
        raise serializers.ValidationError({"connection_type": "Unsupported printer connection type."})
    printer_name = str(settings.get("printer_name") or settings.get("printerName") or "").strip()
    if printer_name and (
        len(printer_name) > 255
        or any(character in printer_name for character in ("\\", "/", ":"))
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in printer_name)
    ):
        raise serializers.ValidationError(
            {"printer_name": "Printer must be an installed local Windows printer, not a remote path."}
        )


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
        if _endpoint_has_sensitive_components(endpoint_url):
            endpoint_url = _MASK
        suffix = terminal_id or endpoint_url
        if suffix:
            return f"{obj.provider} ({suffix})"

        return f"{obj.provider} ({str(obj.id)[-6:]})"

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["settings"] = _mask_settings(representation.get("settings") or {})
        return representation

    def validate_settings(self, value):
        existing = getattr(self.instance, "settings", {}) if self.instance is not None else {}
        settings = dict(_restore_masked_secrets(value or {}, existing))
        settings = _preserve_omitted_secrets(settings, existing)
        _validate_endpoint_components(settings)
        provider = self.initial_data.get("provider") or getattr(
            self.instance, "provider", None
        )
        kind = self.initial_data.get("kind") or getattr(self.instance, "kind", None)
        connection_type = (
            settings.get("connection_type") or settings.get("connectionType") or ""
        ).strip()

        if kind == IntegrationConfig.Kind.PRINTER:
            _validate_printer_target(settings)

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
