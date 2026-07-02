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

    def test_kitchen_ticket_uses_regular_print_mode_and_hides_internal_meta(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866'})
        service = WindowsRawPrinterIntegrationService(config)
        payload = {
            **self._payload(),
            'kitchen_ticket': True,
            'order_label': '#42',
            'restaurant_address': 'Beruniy tumani',
            'restaurant_phone': '+998901234567',
            'restaurant_social': 'Instagram: nyu_york',
            'prep_station_name': 'Kuxnya',
            'waiter_name': 'Adham',
            'guest_count': 3,
            'items': [{'name': 'Shaverma', 'quantity': 1, 'line_total': 24000}],
        }

        lines = service._build_lines(payload)
        raw_payload = service._build_bytes(payload)

        self.assertIn('Buyurtma raqami: 42', '\n'.join(lines))
        self.assertNotIn('Manzil:', '\n'.join(lines))
        self.assertNotIn('Tel:', '\n'.join(lines))
        self.assertNotIn('Instagram:', '\n'.join(lines))
        self.assertNotIn('Oshxona:', '\n'.join(lines))
        self.assertNotIn('Ofitsiant:', '\n'.join(lines))
        self.assertNotIn('Mehmonlar:', '\n'.join(lines))
        self.assertIn(b'\x1b!\x00', raw_payload)
        self.assertNotIn(b'\x1b!\x10', raw_payload)

    def test_text_printing_encodes_cyrillic_without_replacement_chars(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866'})
        service = WindowsRawPrinterIntegrationService(config)

        raw_payload = service._build_text_bytes(text='ШАВЕРМА\nОшхона', qr_code='')

        self.assertIn('ШАВЕРМА'.encode('cp866'), raw_payload)
        self.assertIn('Ошхона'.encode('cp866'), raw_payload)
        self.assertNotIn(b'?', raw_payload)
