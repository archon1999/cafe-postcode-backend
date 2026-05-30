from rest_framework import status
from rest_framework.test import APITestCase

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import CashDesk, Restaurant
from apps.users.models import User


class CashDeskAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.second_restaurant = Restaurant.objects.create(name='Restaurant Two')
        cls.superuser = User.objects.create_superuser(
            username='cashdesk-superuser',
            password='secret123',
            full_name='CashDesk Superuser',
        )
        cls.printer = IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'printer_name': 'POS-80 USB'},
        )
        cls.disabled_printer = IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='disabled-printer',
            is_enabled=False,
            settings={'printer_name': 'Disabled'},
        )
        cls.foreign_printer = IntegrationConfig.objects.create(
            restaurant=cls.second_restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='foreign-printer',
            settings={'printer_name': 'Foreign'},
        )
        cls.payment_integration = IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            settings={'endpoint_url': 'http://127.0.0.1:8080'},
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    @staticmethod
    def _response_value(data, snake_key, camel_key):
        return data.get(snake_key, data.get(camel_key))

    def test_create_cash_desk_accepts_printer_integration(self):
        response = self.client.post(
            '/api/v1/admin/restaurants/cash-desks/',
            {
                'name': 'Main cash desk',
                'printer_integration': str(self.printer.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        cash_desk = CashDesk.objects.get(pk=response.data['id'])
        self.assertEqual(cash_desk.printer_integration_id, self.printer.id)
        self.assertEqual(str(self._response_value(response.data, 'printer_integration', 'printerIntegration')), str(self.printer.id))
        self.assertIn(
            'windows-raw',
            self._response_value(response.data, 'printer_integration_name', 'printerIntegrationName'),
        )

    def test_update_cash_desk_accepts_printer_integration(self):
        cash_desk = CashDesk.objects.create(restaurant=self.restaurant, name='Main cash desk')

        response = self.client.patch(
            f'/api/v1/admin/restaurants/cash-desks/{cash_desk.id}/',
            {'printer_integration': str(self.printer.id)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        cash_desk.refresh_from_db()
        self.assertEqual(cash_desk.printer_integration_id, self.printer.id)

    def test_rejects_disabled_printer_integration(self):
        response = self.client.post(
            '/api/v1/admin/restaurants/cash-desks/',
            {
                'name': 'Main cash desk',
                'printer_integration': str(self.disabled_printer.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('printer_integration' in response.data or 'printerIntegration' in response.data)

    def test_rejects_foreign_printer_integration(self):
        response = self.client.post(
            '/api/v1/admin/restaurants/cash-desks/',
            {
                'name': 'Main cash desk',
                'printer_integration': str(self.foreign_printer.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('printer_integration' in response.data or 'printerIntegration' in response.data)

    def test_rejects_non_printer_integration(self):
        response = self.client.post(
            '/api/v1/admin/restaurants/cash-desks/',
            {
                'name': 'Main cash desk',
                'printer_integration': str(self.payment_integration.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('printer_integration' in response.data or 'printerIntegration' in response.data)
