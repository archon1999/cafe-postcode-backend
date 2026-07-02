from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import base64

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
        self.assertIn('Manzil: Beruniy tumani', '\n'.join(lines))
        self.assertIn('Tel: +998901234567', '\n'.join(lines))
        self.assertIn('Instagram: nyu_york', '\n'.join(lines))
        self.assertNotIn('Oshxona:', '\n'.join(lines))
        self.assertNotIn('Ofitsiant:', '\n'.join(lines))
        self.assertNotIn('Mehmonlar:', '\n'.join(lines))
        self.assertNotIn('Buyurtmangiz uchun rahmat!', '\n'.join(lines))
        self.assertNotIn('Yoqimli ishtaha!', '\n'.join(lines))
        self.assertIn(b'\x1b!\x00', raw_payload)
        self.assertIn(b'\x1b!\x30', raw_payload)

    def test_text_printing_encodes_cyrillic_without_replacement_chars(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866'})
        service = WindowsRawPrinterIntegrationService(config)

        raw_payload = service._build_text_bytes(text='ШАВЕРМА\nОшхона', qr_code='')

        self.assertIn('ШАВЕРМА'.encode('cp866'), raw_payload)
        self.assertIn('Ошхона'.encode('cp866'), raw_payload)
        self.assertNotIn(b'?', raw_payload)

    def test_text_printing_centers_emphasized_header_lines(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866'})
        service = WindowsRawPrinterIntegrationService(config)

        raw_payload = service._build_text_bytes(text='        NYU YORK\n------------------------------------------', qr_code='')

        self.assertIn(b'\x1ba\x01\x1b!\x30NYU YORK\n', raw_payload)

    def test_text_printing_places_qr_before_feed_and_cut(self):
        config = SimpleNamespace(
            provider='windows-raw',
            settings={
                'encoding': 'cp866',
                'feed_lines_before_cut': 3,
                'cut_after_print': True,
                'enable_escpos_qr_command': True,
            },
        )
        service = WindowsRawPrinterIntegrationService(config)

        raw_payload = service._build_text_bytes(text='CHEK', qr_code='https://ofd.soliq.uz/check?r=1')

        qr_index = raw_payload.index(b'\x1d(k')
        feed_index = raw_payload.index(b'\x1bd\x03')
        cut_index = raw_payload.index(b'\x1dV\x00')
        self.assertLess(qr_index, feed_index)
        self.assertLess(feed_index, cut_index)

    def test_text_printing_does_not_emit_escpos_qr_command_by_default(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866', 'cut_after_print': False})
        service = WindowsRawPrinterIntegrationService(config)

        raw_payload = service._build_text_bytes(text='CHEK', qr_code='https://ofd.soliq.uz/check?r=1')

        self.assertNotIn(b'\x1d(k', raw_payload)
        self.assertIn(b'\x1dv0\x00', raw_payload)
        self.assertGreater(len(raw_payload), 8000)

    def test_text_printing_prefers_raster_qr_payload(self):
        config = SimpleNamespace(provider='windows-raw', settings={'encoding': 'cp866', 'cut_after_print': False})
        service = WindowsRawPrinterIntegrationService(config)
        raster_payload = b'\x1ba\x01RASTER-QR\x1ba\x00'

        raw_payload = service._build_text_bytes(
            text='CHEK',
            qr_code='https://ofd.soliq.uz/check?r=1',
            qr_raster_base64=base64.b64encode(raster_payload).decode('ascii'),
        )

        self.assertIn(raster_payload, raw_payload)
        self.assertNotIn(b'\x1d(k', raw_payload)
