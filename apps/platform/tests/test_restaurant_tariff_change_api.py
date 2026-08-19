from rest_framework import status
from rest_framework.test import APITestCase

from apps.platform.models import BusinessPartner, RestaurantEntitlement, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import Role, User


class RestaurantTariffChangeApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partner_role = Role.objects.get(code='business_partner')
        cls.restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        cls.fast_food_admin_role = Role.objects.get(code='fast_food_admin')
        cls.waiter_role = Role.objects.get(code='waiter')
        cls.cashier_role = Role.objects.get(code='fast_food_cashier')

        cls.partner = BusinessPartner.objects.create(
            inn='309999991',
            company_name='Tariff Mapping Partner',
            legal_name='Tariff Mapping Partner LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.partner_user = User.objects.create_user(
            username='tariff-mapping-partner',
            password='secret123',
            full_name='Tariff Mapping Partner',
            role=cls.partner_role,
            business_partner=cls.partner,
            is_active=True,
        )
        cls.restaurant = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Tariff Mapping Restaurant',
            legal_name='Tariff Mapping Restaurant LLC',
            phone='+998901111111',
            address='Tashkent',
            is_active=True,
        )

        cls.source_tariff = Tariff.objects.create(name='Source tariff', is_active=True)
        cls.source_tariff.allowed_roles.set([cls.restaurant_admin_role, cls.waiter_role])
        cls.target_tariff = Tariff.objects.create(name='Target tariff', is_active=True)
        cls.target_tariff.allowed_roles.set([cls.fast_food_admin_role, cls.cashier_role, cls.waiter_role])
        cls.inactive_tariff = Tariff.objects.create(name='Inactive target', is_active=False)
        RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            tariff=cls.source_tariff,
            is_active=True,
        )

        cls.admin_user = User.objects.create_user(
            username='mapping-admin',
            password='admin-secret',
            full_name='Mapping Admin',
            role=cls.restaurant_admin_role,
            restaurant=cls.restaurant,
            is_active=True,
        )
        cls.admin_user.set_pin('1234')
        cls.admin_user.save(update_fields=['pin_code'])
        cls.waiter_user = User.objects.create_user(
            username='mapping-waiter',
            password='waiter-secret',
            full_name='Mapping Waiter',
            role=cls.waiter_role,
            restaurant=cls.restaurant,
            is_active=True,
        )

    def setUp(self):
        self.client.force_authenticate(self.partner_user)

    @property
    def url(self):
        return f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/tariff-change/'

    def test_preview_groups_employees_and_suggests_roles_that_remain_allowed(self):
        response = self.client.get(self.url, {'tariffId': str(self.target_tariff.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['current_tariff']['id'], str(self.source_tariff.id))
        self.assertEqual(response.data['target_tariff']['id'], str(self.target_tariff.id))

        groups = {group['source_role']['code']: group for group in response.data['role_groups']}
        self.assertEqual(groups['restaurant_admin']['suggested_target_role'], None)
        self.assertEqual(groups['waiter']['suggested_target_role']['code'], 'waiter')
        self.assertEqual(groups['restaurant_admin']['employees'][0]['username'], self.admin_user.username)

    def test_apply_requires_complete_mapping_and_preserves_credentials(self):
        admin_password = self.admin_user.password
        admin_pin = self.admin_user.pin_code
        admin_username = self.admin_user.username
        waiter_password = self.waiter_user.password

        incomplete_response = self.client.post(
            self.url,
            {
                'tariffId': str(self.target_tariff.id),
                'roleMappings': [
                    {
                        'sourceRoleId': str(self.restaurant_admin_role.id),
                        'targetRoleId': str(self.fast_food_admin_role.id),
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(incomplete_response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            self.url,
            {
                'tariffId': str(self.target_tariff.id),
                'roleMappings': [
                    {
                        'sourceRoleId': str(self.restaurant_admin_role.id),
                        'targetRoleId': str(self.fast_food_admin_role.id),
                    },
                    {
                        'sourceRoleId': str(self.waiter_role.id),
                        'targetRoleId': str(self.cashier_role.id),
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['updated_users'], 2)

        self.admin_user.refresh_from_db()
        self.waiter_user.refresh_from_db()
        self.restaurant.entitlement.refresh_from_db()
        self.assertEqual(self.admin_user.role_id, self.fast_food_admin_role.id)
        self.assertEqual(self.waiter_user.role_id, self.cashier_role.id)
        self.assertEqual(self.restaurant.entitlement.tariff_id, self.target_tariff.id)
        self.assertFalse(self.restaurant.entitlement.is_custom)
        self.assertEqual(self.admin_user.username, admin_username)
        self.assertEqual(self.admin_user.password, admin_password)
        self.assertEqual(self.admin_user.pin_code, admin_pin)
        self.assertEqual(self.waiter_user.password, waiter_password)

    def test_apply_rejects_role_that_is_not_allowed_by_target_tariff(self):
        response = self.client.post(
            self.url,
            {
                'tariffId': str(self.target_tariff.id),
                'roleMappings': [
                    {
                        'sourceRoleId': str(self.restaurant_admin_role.id),
                        'targetRoleId': str(self.restaurant_admin_role.id),
                    },
                    {
                        'sourceRoleId': str(self.waiter_role.id),
                        'targetRoleId': str(self.waiter_role.id),
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.admin_user.refresh_from_db()
        self.assertEqual(self.admin_user.role_id, self.restaurant_admin_role.id)

    def test_inactive_target_tariff_is_rejected(self):
        response = self.client.get(self.url, {'tariffId': str(self.inactive_tariff.id)})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
