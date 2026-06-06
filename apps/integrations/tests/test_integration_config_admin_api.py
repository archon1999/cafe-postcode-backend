from rest_framework import status
from rest_framework.test import APITestCase

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import CashDesk, PrepStation, Restaurant
from apps.users.models import User


class IntegrationConfigAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.superuser = User.objects.create_superuser(
            username='integration-superuser',
            password='secret123',
            full_name='Integration Superuser',
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_delete_integration_config_clears_linked_cash_desk_and_prep_station(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'printer_name': 'POS-80 USB'},
        )
        cash_desk = CashDesk.objects.create(
            restaurant=self.restaurant,
            name='Main cash desk',
            printer_integration=printer,
        )
        prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Kitchen',
            printer_integration=printer,
        )

        response = self.client.delete(f'/api/v1/admin/integrations/configs/{printer.id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.data)
        self.assertFalse(IntegrationConfig.objects.filter(pk=printer.id).exists())
        cash_desk.refresh_from_db()
        prep_station.refresh_from_db()
        self.assertIsNone(cash_desk.printer_integration_id)
        self.assertIsNone(prep_station.printer_integration_id)
