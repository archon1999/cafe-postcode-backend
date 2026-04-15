from django.utils import timezone

from .windows_raw_printer import WindowsRawPrinterIntegrationService


class QzTrayPrinterIntegrationService:
    """Creates client-side QZ Tray print jobs for ESC/POS printers."""

    def __init__(self, config):
        self.config = config
        self.settings = dict(config.settings or {})

    def _connection_type(self) -> str:
        explicit = self.settings.get('connection_type') or self.settings.get('connectionType')
        if explicit:
            return str(explicit)
        return 'socket' if self.settings.get('host') else 'system_printer'

    def _paper_width(self) -> int:
        try:
            return int(self.settings.get('paper_width_mm') or self.settings.get('paperWidthMm') or 80)
        except (TypeError, ValueError):
            return 80

    def _port(self) -> int:
        try:
            return int(self.settings.get('port') or 9100)
        except (TypeError, ValueError):
            return 9100

    def _build_config(self) -> dict:
        connection_type = self._connection_type()
        config = {
            'connection_type': connection_type,
            'paper_width_mm': self._paper_width(),
            'encoding': self.settings.get('encoding') or 'cp437',
            'cut_after_print': bool(self.settings.get('cut_after_print', True)),
        }

        if connection_type == 'socket':
            host = str(self.settings.get('host') or '').strip()
            if not host:
                raise ValueError('QZ Tray printer host is not configured.')
            config['host'] = host
            config['port'] = self._port()
            return config

        printer_name = str(self.settings.get('printer_name') or self.settings.get('printerName') or '').strip()
        if not printer_name:
            raise ValueError('QZ Tray printer name is not configured.')
        config['printer_name'] = printer_name
        return config

    def print_prebill(self, *, order, payload):
        raw_payload = WindowsRawPrinterIntegrationService(self.config)._build_bytes(payload)

        return {
            'ok': True,
            'provider': self.config.provider,
            'mode': self.config.mode,
            'requires_client_print': True,
            'created_at': timezone.now().isoformat(),
            'printed_at': None,
            'print_job': {
                'type': 'qz-tray',
                'format': 'raw',
                'language': 'escpos',
                'flavor': 'hex',
                'data': raw_payload.hex(),
                'encoding': self.settings.get('encoding') or 'cp437',
                'config': self._build_config(),
            },
            'order_id': str(order.id),
            'order_number': getattr(order, 'order_number', ''),
        }
