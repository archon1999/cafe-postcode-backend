from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.restaurants.models import Restaurant
from apps.users.models import User


class MyRestaurantAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.second_restaurant = Restaurant.objects.create(name='Restaurant Two')
        cls.superuser = User.objects.create_superuser(
            username='my-restaurant-superuser',
            password='secret123',
            full_name='My Restaurant Superuser',
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.second_restaurant.id))

    def test_superuser_my_restaurant_uses_selected_restaurant_scope(self):
        response = self.client.get('/api/v1/admin/restaurants/my-restaurant/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(str(response.data['id']), str(self.second_restaurant.id))

    def test_superuser_updates_selected_restaurant_settings(self):
        response = self.client.put(
            '/api/v1/admin/restaurants/settings/',
            {
                'name': self.second_restaurant.name,
                'legal_name': self.second_restaurant.legal_name,
                'tax_number': self.second_restaurant.tax_number,
                'phone': self.second_restaurant.phone,
                'address': self.second_restaurant.address,
                'faktura_payload': self.second_restaurant.faktura_payload,
                'service_fee_enabled': True,
                'service_fee_percent': '7.50',
                'vat_enabled': self.second_restaurant.vat_enabled,
                'vat_percent': self.second_restaurant.vat_percent,
                'is_active': self.second_restaurant.is_active,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.second_restaurant.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertTrue(self.second_restaurant.service_fee_enabled)
        self.assertEqual(self.second_restaurant.service_fee_percent, Decimal('7.50'))
        self.assertFalse(self.restaurant.service_fee_enabled)
