from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.integrations.services.windows_raw_printer import WindowsRawPrinterIntegrationService


class WindowsRawPrinterIntegrationServiceTests(SimpleTestCase):
    def _payload(self):
        return {
            'restaurant_name': 'Test restaurant',
            'order_number': 42,
            'channel_label': 'Zal',
            'table_label': '',
            'waiter_name': '',
            'printed_at_label': '2026-06-06 12:00',
            'items': [{'name': 'Lagmon', 'quantity': 1, 'line_total': 25000}],
            'subtotal': 25000,
            'service_fee': 0,
            'total': 25000,
            'order_note': '',
        }

    def _order(self):
        return SimpleNamespace(
            id=uuid4(),
            order_number=42,
            restaurant=SimpleNamespace(id=uuid4()),
        )

    def test_legacy_usb_config_without_transport_uses_local_agent(self):
        config = SimpleNamespace(
            provider='windows-raw',
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'POS-80 USB',
                'encoding': 'cp1251',
            },
        )
        service = WindowsRawPrinterIntegrationService(config)

        with patch('apps.integrations.services.windows_raw_printer.LocalAgentCommandService') as command_service_cls:
            command_service_cls.return_value.printer_raw.return_value = {'ok': True}
            result = service.print_prebill(order=self._order(), payload=self._payload())

        self.assertTrue(result['ok'])
        command_service_cls.return_value.printer_raw.assert_called_once()
        raw_payload = command_service_cls.return_value.printer_raw.call_args.kwargs['payload']
        self.assertEqual(raw_payload['connectionType'], 'system_printer')
        self.assertEqual(raw_payload['printerName'], 'POS-80 USB')

    def test_legacy_lan_config_without_transport_uses_local_agent(self):
        config = SimpleNamespace(
            provider='windows-raw',
            settings={
                'connection_type': 'socket',
                'host': '192.168.0.254',
                'port': 9100,
                'encoding': 'cp1251',
            },
        )
        service = WindowsRawPrinterIntegrationService(config)

        with patch('apps.integrations.services.windows_raw_printer.LocalAgentCommandService') as command_service_cls:
            command_service_cls.return_value.printer_raw.return_value = {'ok': True}
            result = service.print_prebill(order=self._order(), payload=self._payload())

        self.assertTrue(result['ok'])
        command_service_cls.return_value.printer_raw.assert_called_once()
        raw_payload = command_service_cls.return_value.printer_raw.call_args.kwargs['payload']
        self.assertEqual(raw_payload['connectionType'], 'socket')
        self.assertEqual(raw_payload['host'], '192.168.0.254')
        self.assertEqual(raw_payload['port'], 9100)

    def test_explicit_direct_transport_does_not_use_local_agent(self):
        config = SimpleNamespace(
            provider='windows-raw',
            settings={
                'transport': 'direct',
                'connection_type': 'socket',
                'host': '192.168.0.254',
                'port': 9100,
                'encoding': 'cp1251',
            },
        )
        service = WindowsRawPrinterIntegrationService(config)

        self.assertFalse(service._use_local_agent())
