from apps.integrations.models import IntegrationConfig


def get_printer_integration_display(integration: IntegrationConfig | None) -> str:
    if integration is None:
        return ''

    settings = integration.settings or {}
    printer_name = settings.get('printer_name') or settings.get('printerName')
    host = settings.get('host')
    port = settings.get('port')

    if host:
        suffix = f'{host}:{port}' if port else str(host)
    else:
        suffix = printer_name

    return f'{integration.provider} ({suffix})' if suffix else integration.provider
