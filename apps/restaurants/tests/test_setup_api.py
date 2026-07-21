from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.integrations.models import IntegrationConfig
from apps.local_agents.models import LocalAgent
from apps.printing.models import PrintTemplate
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation, Restaurant
from apps.users.models import User


class RestaurantSetupApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Setup Restaurant', auth_code='S3TUP1')
        cls.superuser = User.objects.create_superuser(
            username='setup-superuser', password='secret123', full_name='Setup Superuser'
        )

    def setUp(self):
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_readiness_exposes_blocking_steps_and_installer_manifest(self):
        self.assertTrue(
            DistributionPoint.objects.filter(
                restaurant=self.restaurant,
                kind=DistributionPoint.Kind.DELIVERY,
                is_active=True,
            ).exists()
        )
        response = self.client.get('/api/v1/admin/restaurants/setup/readiness/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['ready'])
        self.assertGreater(response.data['blockingIssueCount'], 0)
        self.assertEqual(response.data['installerManifest']['restaurantCode'], self.restaurant.auth_code)
        self.assertNotIn('agentToken', response.data['installerManifest'])
        self.assertEqual(response.data['installerManifest']['localHttpListen'], '127.0.0.1:18181')
        self.assertEqual(
            {step['id'] for step in response.data['steps']},
            {'profile', 'staff', 'service_points', 'menu', 'integrations', 'coordinator', 'printing'},
        )

    def test_missing_card_payment_integration_is_warning(self):
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'tax_number': '312217845'},
        )
        CashDesk.objects.create(
            restaurant=self.restaurant,
            name='Kassa',
            receipt_printer_enabled=False,
            enabled_payment_methods=['cash', 'card'],
            fiscal_integration=fiscal,
        )

        response = self.client.get('/api/v1/admin/restaurants/setup/readiness/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        integrations = next(step for step in response.data['steps'] if step['id'] == 'integrations')
        payment_issue = next(
            issue for issue in integrations['issues'] if issue['code'] == 'cash_desk_payment_missing'
        )
        self.assertFalse(payment_issue['blocking'])
        self.assertEqual(integrations['status'], 'warning')

    def test_offline_local_agent_is_blocking(self):
        LocalAgent.issue_for_restaurant(restaurant=self.restaurant)

        response = self.client.get('/api/v1/admin/restaurants/setup/readiness/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        coordinator = next(step for step in response.data['steps'] if step['id'] == 'coordinator')
        offline_issue = next(issue for issue in coordinator['issues'] if issue['code'] == 'local_agent_offline')
        self.assertTrue(offline_issue['blocking'])
        self.assertEqual(coordinator['status'], 'blocked')

    def test_apply_multi_terminal_baseline_is_idempotent_and_binds_devices(self):
        payload = {
            'preset': 'multi_terminal',
            'cashDesks': [
                {
                    'name': 'Kassa 1',
                    'location': 'Entrance',
                    'enabledPaymentMethods': ['cash', 'card', 'mixed'],
                    'receiptPrinterEnabled': True,
                    'printer': {
                        'name': 'Kassa 1 printer',
                        'provider': 'windows-raw',
                        'settings': {'host': '192.168.1.51', 'port': 9100},
                    },
                    'payment': {
                        'name': 'MARTA main',
                        'provider': 'marta-softpos',
                        'settings': {'endpointUrl': 'http://192.168.1.60:8090'},
                    },
                    'fiscal': {
                        'name': 'Fiscal Drive main',
                        'provider': 'fiscal-drive-service',
                        'settings': {'taxNumber': '309123456'},
                    },
                },
                {
                    'name': 'Kassa 2',
                    'location': 'Terrace',
                    'enabledPaymentMethods': ['cash'],
                    'receiptPrinterEnabled': False,
                },
            ],
            'prepStations': [
                {
                    'name': 'Oshxona',
                    'kind': 'kitchen',
                    'printer': {
                        'name': 'Kitchen printer',
                        'provider': 'windows-raw',
                        'settings': {'host': '192.168.1.52', 'port': 9100},
                    },
                }
            ],
            'createTakeaway': True,
            'createDelivery': True,
        }

        first = self.client.post('/api/v1/admin/restaurants/setup/apply/', payload, format='json')
        second = self.client.post('/api/v1/admin/restaurants/setup/apply/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertEqual(CashDesk.objects.filter(restaurant=self.restaurant).count(), 2)
        self.assertEqual(PrepStation.objects.filter(restaurant=self.restaurant).count(), 1)
        self.assertEqual(IntegrationConfig.objects.filter(restaurant=self.restaurant).count(), 4)
        self.assertEqual(DistributionPoint.objects.filter(restaurant=self.restaurant).count(), 2)
        self.assertEqual(PrintTemplate.objects.filter(restaurant=self.restaurant).count(), 3)
        primary = CashDesk.objects.get(restaurant=self.restaurant, name='Kassa 1')
        self.assertEqual(primary.printer_integration.name, 'Kassa 1 printer')
        self.assertEqual(primary.payment_integration.name, 'MARTA main')
        self.assertEqual(primary.fiscal_integration.name, 'Fiscal Drive main')
        kitchen = PrepStation.objects.get(restaurant=self.restaurant, name='Oshxona')
        self.assertEqual(kitchen.printer_integration.name, 'Kitchen printer')

    def test_apply_reuses_equivalent_integrations_across_resources(self):
        shared_printer = {'provider': 'windows-raw', 'settings': {'host': '192.168.1.50', 'port': 9100}}
        shared_payment = {'provider': 'marta-softpos', 'settings': {'endpointUrl': 'http://192.168.1.60:8090'}}
        shared_fiscal = {'provider': 'fiscal-drive-service', 'settings': {'taxNumber': '309123456'}}
        payload = {
            'cashDesks': [
                {
                    'name': 'Kassa 1',
                    'enabledPaymentMethods': ['cash', 'card'],
                    'printer': {'name': 'Receipt printer', **shared_printer},
                    'payment': {'name': 'MARTA 1', **shared_payment},
                    'fiscal': {'name': 'Fiscal 1', **shared_fiscal},
                },
                {
                    'name': 'Kassa 2',
                    'enabledPaymentMethods': ['cash', 'card'],
                    'printer': {'name': 'Same receipt printer', **shared_printer},
                    'payment': {'name': 'MARTA 2', **shared_payment},
                    'fiscal': {'name': 'Fiscal 2', **shared_fiscal},
                },
            ],
            'prepStations': [
                {
                    'name': 'Oshxona',
                    'kind': 'kitchen',
                    'printer': {'name': 'Kitchen alias', **shared_printer},
                }
            ],
        }

        response = self.client.post('/api/v1/admin/restaurants/setup/apply/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(IntegrationConfig.objects.filter(restaurant=self.restaurant).count(), 3)
        desks = list(CashDesk.objects.filter(restaurant=self.restaurant).order_by('name'))
        station = PrepStation.objects.get(restaurant=self.restaurant, name='Oshxona')
        self.assertEqual(desks[0].printer_integration_id, desks[1].printer_integration_id)
        self.assertEqual(desks[0].printer_integration_id, station.printer_integration_id)
        self.assertEqual(desks[0].payment_integration_id, desks[1].payment_integration_id)
        self.assertEqual(desks[0].fiscal_integration_id, desks[1].fiscal_integration_id)

    def test_readiness_exposes_existing_quick_setup_values_and_resource_ids(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'POS-80 USB',
                'encoding': 'cp1251',
            },
        )
        payment = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            settings={'endpoint_url': 'http://192.168.1.133:8090', 'tax_number': '312217845'},
        )
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'tax_number': '312217845', 'factory_id': 'fiscal-device-1'},
        )
        kitchen_printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            is_enabled=False,
            settings={'connection_type': 'socket', 'host': '192.168.0.254', 'port': 9100},
        )
        desk = CashDesk.objects.create(
            restaurant=self.restaurant,
            name='Kassa',
            printer_integration=printer,
            payment_integration=payment,
            fiscal_integration=fiscal,
        )
        station = PrepStation.objects.create(restaurant=self.restaurant, name='Oshxona', kind='kitchen')

        response = self.client.get('/api/v1/admin/restaurants/setup/readiness/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        quick_setup = response.data['quickSetup']
        self.assertEqual(quick_setup['fiscalTaxNumber'], '312217845')
        self.assertEqual(quick_setup['martaTaxNumber'], '312217845')
        self.assertEqual(quick_setup['cashDesks'][0]['id'], str(desk.id))
        self.assertEqual(quick_setup['cashDesks'][0]['name'], 'Kassa')
        self.assertEqual(quick_setup['cashDesks'][0]['printerTarget'], 'POS-80 USB')
        self.assertEqual(quick_setup['cashDesks'][0]['printerIntegrationId'], str(printer.id))
        self.assertEqual(quick_setup['prepStations'][0]['id'], str(station.id))
        self.assertEqual(quick_setup['prepStations'][0]['printerTarget'], '192.168.0.254')
        self.assertEqual(quick_setup['prepStations'][0]['printerIntegrationId'], str(kitchen_printer.id))

    def test_apply_updates_existing_ids_preserves_hidden_settings_and_removes_setup_shadow(self):
        payment = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            settings={
                'endpoint_url': 'http://192.168.1.133:8090',
                'hmac_secret': 'secret',
                'transport': 'local-agent',
            },
        )
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={
                'tax_number': '312217845',
                'factory_id': 'fiscal-device-1',
                'terminal_id': 'terminal-1',
                'transport': 'local-agent',
            },
        )
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='Kassa 1 Fiscal Drive',
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'tax_number': '312217845', 'transport': 'local-agent'},
        )
        desk = CashDesk.objects.create(
            restaurant=self.restaurant,
            name='Kassa',
            payment_integration=payment,
            fiscal_integration=fiscal,
            receipt_printer_enabled=False,
            enabled_payment_methods=['cash'],
        )
        station = PrepStation.objects.create(restaurant=self.restaurant, name='Oshxona', kind='kitchen')
        payload = {
            'cashDesks': [
                {
                    'id': str(desk.id),
                    'name': 'Kassa',
                    'enabledPaymentMethods': ['cash'],
                    'receiptPrinterEnabled': False,
                    'payment': {
                        'id': str(payment.id),
                        'name': 'Kassa MARTA',
                        'provider': 'marta-softpos',
                        'settings': {'taxNumber': '309123456'},
                    },
                    'fiscal': {
                        'id': str(fiscal.id),
                        'name': 'Kassa Fiscal Drive',
                        'provider': 'fiscal-drive-service',
                        'settings': {'taxNumber': '312217845'},
                    },
                }
            ],
            'prepStations': [{'id': str(station.id), 'name': 'Oshxona', 'kind': 'kitchen'}],
        }

        response = self.client.post('/api/v1/admin/restaurants/setup/apply/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(CashDesk.objects.filter(restaurant=self.restaurant).count(), 1)
        self.assertFalse(CashDesk.objects.filter(restaurant=self.restaurant, name='Kassa 1').exists())
        self.assertEqual(
            IntegrationConfig.objects.filter(
                restaurant=self.restaurant,
                kind=IntegrationConfig.Kind.FISCAL,
                provider='fiscal-drive-service',
            ).count(),
            1,
        )
        fiscal.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.settings['tax_number'], '309123456')
        self.assertEqual(payment.settings['endpoint_url'], 'http://192.168.1.133:8090')
        self.assertEqual(payment.settings['hmac_secret'], 'secret')
        self.assertEqual(fiscal.settings['factory_id'], 'fiscal-device-1')
        self.assertEqual(fiscal.settings['terminal_id'], 'terminal-1')

    def test_menu_readiness_uses_category_prep_station_not_item_override(self):
        station = PrepStation.objects.create(restaurant=self.restaurant, name='Kitchen', kind='kitchen')
        category = CatalogCategory.objects.create(restaurant=self.restaurant, name='Main dishes')
        CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=category,
            prep_station=station,
            name='Osh',
            price=30000,
        )

        missing = self.client.get('/api/v1/admin/restaurants/setup/readiness/')
        category.prep_station = station
        category.save(update_fields=['prep_station', 'updated_at'])
        ready = self.client.get('/api/v1/admin/restaurants/setup/readiness/')

        missing_menu = next(step for step in missing.data['steps'] if step['id'] == 'menu')
        ready_menu = next(step for step in ready.data['steps'] if step['id'] == 'menu')
        self.assertIn('menu_category_without_prep_station', {item['code'] for item in missing_menu['issues']})
        self.assertNotIn('menu_category_without_prep_station', {item['code'] for item in ready_menu['issues']})
