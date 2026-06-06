from rest_framework import status
from rest_framework.test import APITestCase

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import PrepStation, Restaurant
from apps.users.models import User


class PrepStationAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.superuser = User.objects.create_superuser(
            username='prepstation-superuser',
            password='secret123',
            full_name='PrepStation Superuser',
        )
        cls.usb_printer = IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'printer_name': 'POS-80 USB'},
        )
        cls.lan_printer = IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'host': '192.168.1.60', 'port': 9100},
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    @staticmethod
    def _response_value(data, snake_key, camel_key):
        return data.get(snake_key, data.get(camel_key))

    def test_prep_station_printer_integration_name_includes_usb_printer_name(self):
        prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Kitchen',
            printer_integration=self.usb_printer,
        )

        response = self.client.get(f'/api/v1/admin/restaurants/prep-stations/{prep_station.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn(
            'POS-80 USB',
            self._response_value(response.data, 'printer_integration_name', 'printerIntegrationName'),
        )

    def test_prep_station_printer_integration_name_includes_lan_host_and_port(self):
        prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Kitchen',
            printer_integration=self.lan_printer,
        )

        response = self.client.get(f'/api/v1/admin/restaurants/prep-stations/{prep_station.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn(
            '192.168.1.60:9100',
            self._response_value(response.data, 'printer_integration_name', 'printerIntegrationName'),
        )
