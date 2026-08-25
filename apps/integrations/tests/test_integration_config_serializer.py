from django.test import TestCase

from apps.integrations.api.admin.serializers import IntegrationConfigSerializer
from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import Restaurant


class IntegrationConfigSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')

    def test_windows_raw_system_printer_uses_local_agent_transport(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.PRINTER,
                'provider': 'windows-raw',
                'is_enabled': True,
                'settings': {
                    'connection_type': 'system_printer',
                    'printer_name': 'POS-80 USB',
                    'transport_type': 'direct',
                    'use_local_agent': False,
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data['settings'],
            {
                'connection_type': 'system_printer',
                'printer_name': 'POS-80 USB',
                'transport': 'local-agent',
                'encoding': 'cp1251',
                'code_page': 46,
                'print_mode': 'text',
                'qr_mode': 'native',
                'raster_font': 'go_mono',
            },
        )

    def test_printer_output_modes_accept_aliases_and_are_canonicalized(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.PRINTER,
                'provider': 'windows-raw',
                'is_enabled': True,
                'settings': {
                    'connection_type': 'system_printer',
                    'printer_name': 'XP-H200N',
                    'printMode': ' RASTER ',
                    'qrMode': ' raster ',
                    'rasterFont': ' Noto_Sans ',
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        settings = serializer.validated_data['settings']
        self.assertEqual(settings['print_mode'], 'raster')
        self.assertEqual(settings['qr_mode'], 'raster')
        self.assertEqual(settings['raster_font'], 'noto_sans')
        self.assertNotIn('printMode', settings)
        self.assertNotIn('qrMode', settings)
        self.assertNotIn('rasterFont', settings)

    def test_printer_rejects_unknown_output_modes(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.PRINTER,
                'provider': 'windows-raw',
                'is_enabled': True,
                'settings': {
                    'connection_type': 'system_printer',
                    'printer_name': 'POS-80 USB',
                    'print_mode': 'pdf',
                    'qr_mode': 'native',
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('print_mode', serializer.errors['settings'])

    def test_printer_rejects_unknown_raster_font(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.PRINTER,
                'provider': 'windows-raw',
                'is_enabled': True,
                'settings': {
                    'connection_type': 'system_printer',
                    'printer_name': 'POS-80 USB',
                    'raster_font': 'comic_sans',
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('raster_font', serializer.errors['settings'])

    def test_fiscal_drive_removes_parser_normalized_transport_aliases(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.FISCAL,
                'provider': 'fiscal-drive-service',
                'is_enabled': True,
                'settings': {
                    'terminal_id': 'T-1',
                    'transport_type': 'direct',
                    'use_local_agent': False,
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data['settings'],
            {'terminal_id': 'T-1', 'transport': 'local-agent'},
        )

    def test_windows_raw_socket_uses_local_agent_transport(self):
        instance = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            is_enabled=True,
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'POS-80 USB',
                'transport': 'local-agent',
            },
        )
        serializer = IntegrationConfigSerializer(
            instance,
            data={
                'kind': IntegrationConfig.Kind.PRINTER,
                'provider': 'windows-raw',
                'is_enabled': True,
                'settings': {
                    'connection_type': 'socket',
                    'host': '192.168.1.50',
                    'port': 9100,
                    'transport': 'local-agent',
                },
            },
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['settings']['transport'], 'local-agent')
        self.assertEqual(serializer.validated_data['settings']['encoding'], 'cp1251')
        self.assertEqual(serializer.validated_data['settings']['code_page'], 46)

    def test_printer_display_name_includes_lan_endpoint(self):
        instance = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            is_enabled=True,
            settings={'connection_type': 'socket', 'host': '192.168.0.254', 'port': 9100},
        )

        data = IntegrationConfigSerializer(instance).data

        self.assertEqual(data['display_name'], 'windows-raw (LAN TCP/IP: 192.168.0.254:9100)')

    def test_printer_display_name_includes_usb_printer_name(self):
        instance = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            is_enabled=True,
            settings={'connection_type': 'system_printer', 'printer_name': 'POS-80 USB'},
        )

        data = IntegrationConfigSerializer(instance).data

        self.assertEqual(data['display_name'], 'windows-raw (Windows/USB: POS-80 USB)')

    def test_unikassa_fiscal_provider_is_rejected(self):
        serializer = IntegrationConfigSerializer(
            data={
                'kind': IntegrationConfig.Kind.FISCAL,
                'provider': 'unikassa',
                'is_enabled': True,
                'settings': {},
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('provider', serializer.errors)
