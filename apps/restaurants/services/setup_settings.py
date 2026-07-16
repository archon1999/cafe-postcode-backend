import json

from apps.integrations.models import IntegrationConfig


def canonical_settings(settings):
    values = dict(settings or {})
    aliases = {
        "endpointUrl": "endpoint_url",
        "taxNumber": "tax_number",
        "connectionType": "connection_type",
        "printerName": "printer_name",
        "codePage": "code_page",
        "paperWidthMm": "paper_width_mm",
        "cutAfterPrint": "cut_after_print",
        "terminalId": "terminal_id",
        "factoryId": "factory_id",
    }
    for alias, canonical in aliases.items():
        if alias in values:
            values[canonical] = values.pop(alias)
    return values


def normalized_settings(*, kind, provider, settings):
    values = canonical_settings(settings)
    if provider in {"windows-raw", "marta-softpos", "fiscal-drive-service"}:
        values["transport"] = "local-agent"
    if kind == IntegrationConfig.Kind.PRINTER:
        values.setdefault("encoding", "cp1251")
        values.setdefault("code_page", 46)
    return values


def merge_setup_settings(*, kind, provider, current, updates):
    values = canonical_settings(current)
    values.update(canonical_settings(updates))
    if kind == IntegrationConfig.Kind.PRINTER:
        if values.get("connection_type") == "socket":
            values.pop("printer_name", None)
        elif values.get("connection_type") == "system_printer":
            values.pop("host", None)
            values.pop("port", None)
    return normalized_settings(kind=kind, provider=provider, settings=values)


def read_setting(config, *keys):
    if config is None:
        return ""
    settings = canonical_settings(config.settings)
    for key in keys:
        value = settings.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def printer_target(config):
    if config is None:
        return ""
    settings = canonical_settings(config.settings)
    if settings.get("connection_type") == "socket" or settings.get("host"):
        host = str(settings.get("host") or "").strip()
        port = int(settings.get("port") or 9100)
        return f"{host}:{port}" if host and port != 9100 else host
    return str(settings.get("printer_name") or "").strip()


def integration_fingerprint(*, kind, provider, settings, is_enabled):
    return (
        str(kind),
        str(provider),
        bool(is_enabled),
        json.dumps(
            settings or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
