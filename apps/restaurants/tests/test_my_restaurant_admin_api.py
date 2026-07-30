from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


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
        pos_permission = Permission.objects.get(code='pos_takeaway_menu.view')
        cls.pos_role = Role.objects.create(
            code='my_restaurant_pos_only_test',
            name='My restaurant POS only test',
            is_system=False,
        )
        cls.pos_role.permissions.set([pos_permission])
        entitlement, _ = RestaurantEntitlement.objects.update_or_create(
            restaurant=cls.second_restaurant,
            defaults={'is_active': True},
        )
        entitlement.permissions.set([pos_permission])
        entitlement.allowed_roles.set([cls.pos_role])
        cls.pos_user = User.objects.create_user(
            username='my-restaurant-pos-user',
            password='secret123',
            full_name='My Restaurant POS User',
            restaurant=cls.second_restaurant,
            role=cls.pos_role,
            is_active=True,
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
                'phone': self.second_restaurant.phone,
                'address': self.second_restaurant.address,
                'service_fee_enabled': True,
                'service_fee_percent': '7.50',
                'vat_enabled': self.second_restaurant.vat_enabled,
                'vat_percent': self.second_restaurant.vat_percent,
                'pos_monitor_variant': Restaurant.PosMonitorVariant.LIGHT_COMPACT,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.second_restaurant.refresh_from_db()
        self.restaurant.refresh_from_db()
        self.assertTrue(self.second_restaurant.service_fee_enabled)
        self.assertEqual(self.second_restaurant.service_fee_percent, Decimal('7.50'))
        self.assertEqual(self.second_restaurant.pos_monitor_variant, Restaurant.PosMonitorVariant.LIGHT_COMPACT)
        self.assertFalse(self.restaurant.service_fee_enabled)

    def test_pos_only_user_cannot_read_admin_restaurant_profile(self):
        self.client.force_authenticate(self.pos_user)
        self.client.credentials()

        response = self.client.get('/api/v1/admin/restaurants/my-restaurant/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_self_service_settings_reject_platform_owned_fields(self):
        target_tariff = Tariff.objects.create(name='Forbidden self-service tariff', is_active=True)
        original_auth_code = self.second_restaurant.auth_code
        original_faktura_payload = self.second_restaurant.faktura_payload

        response = self.client.patch(
            '/api/v1/admin/restaurants/settings/',
            {
                'tariffId': str(target_tariff.id),
                'authCode': 'HACKED',
                'isActive': False,
                'fakturaPayload': {'CompanyName': 'Hacked'},
                'legalName': 'Hacked legal name',
                'taxNumber': '000000000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.second_restaurant.refresh_from_db()
        entitlement = getattr(self.second_restaurant, 'entitlement', None)
        self.assertNotEqual(getattr(entitlement, 'tariff_id', None), target_tariff.id)
        self.assertEqual(self.second_restaurant.auth_code, original_auth_code)
        self.assertTrue(self.second_restaurant.is_active)
        self.assertEqual(self.second_restaurant.faktura_payload, original_faktura_payload)
        self.assertNotEqual(self.second_restaurant.legal_name, 'Hacked legal name')
        self.assertNotEqual(self.second_restaurant.tax_number, '000000000')
