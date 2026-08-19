from rest_framework import status
from rest_framework.test import APITestCase

from apps.platform.models import BusinessPartner, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


class PlatformTariffActivationApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product_owner_role = Role.objects.get(code='product_owner')
        cls.business_partner_role = Role.objects.get(code='business_partner')
        cls.restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        cls.fast_food_admin_role = Role.objects.get(code='fast_food_admin')
        cls.waiter_role = Role.objects.get(code='waiter')
        cls.fast_food_cashier_role = Role.objects.get(code='fast_food_cashier')
        cls.custom_tariff_permission = Permission.objects.get(code='restaurants.custom_tariff')

        cls.product_owner_user = User.objects.create_user(
            username='platform-owner', password='secret123', full_name='Platform Owner',
            role=cls.product_owner_role, is_staff=True, is_active=True,
        )
        cls.partner = BusinessPartner.objects.create(
            inn='123456789', company_name='Partner LLC', legal_name='Partner LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.business_partner_user = User.objects.create_user(
            username='partner-owner', password='secret123', full_name='Partner Owner',
            role=cls.business_partner_role, business_partner=cls.partner,
            is_staff=True, is_active=True,
        )

        cls.restaurant_tariff = Tariff.objects.create(
            name='API Restaurant Tariff', description='Restaurant tariff', is_active=True,
        )
        cls.restaurant_tariff.allowed_roles.set([cls.restaurant_admin_role, cls.waiter_role])
        cls.restaurant_tariff.permissions.set(
            {
                *cls.restaurant_admin_role.permissions.values_list('id', flat=True),
                *cls.waiter_role.permissions.values_list('id', flat=True),
            }
        )
        cls.fast_food_tariff = Tariff.objects.create(
            name='API Fast Food Tariff', description='Fast food tariff', is_active=True,
        )
        cls.fast_food_tariff.allowed_roles.set([cls.fast_food_admin_role, cls.fast_food_cashier_role])
        cls.fast_food_tariff.permissions.set(
            {
                *cls.fast_food_admin_role.permissions.values_list('id', flat=True),
                *cls.fast_food_cashier_role.permissions.values_list('id', flat=True),
            }
        )
        cls.inactive_tariff = Tariff.objects.create(
            name='Inactive Tariff', description='Inactive', is_active=False,
        )
        cls.restaurant = Restaurant.objects.create(
            business_partner=cls.partner, name='Activation Restaurant',
            legal_name='Activation Restaurant LLC', phone='+998900000001',
            address='Tashkent', is_active=False,
        )

    def test_business_partner_can_fetch_only_active_tariff_options(self):
        self.client.force_authenticate(self.business_partner_user)
        response = self.client.get('/api/v1/admin/platform/tariff-options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tariff_names = {item['name'] for item in response.data}
        self.assertEqual(tariff_names, {self.restaurant_tariff.name, self.fast_food_tariff.name})
        self.assertNotIn('monthly_price', response.data[0])
        self.assertNotIn('yearly_price', response.data[0])

    def test_business_partner_can_fetch_activation_options(self):
        self.client.force_authenticate(self.business_partner_user)
        response = self.client.get('/api/v1/admin/platform/restaurants/activation-options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        role_codes = {item['code'] for item in response.data['roles']}
        self.assertIn('restaurant_admin', role_codes)
        self.assertIn('fast_food_admin', role_codes)
        self.assertNotIn('product_owner', role_codes)
        self.assertFalse(response.data['custom_tariff_allowed'])

    def test_activation_options_marks_custom_tariff_allowed_when_partner_has_permission(self):
        self.partner.extra_permissions.add(self.custom_tariff_permission)
        self.client.force_authenticate(self.business_partner_user)
        response = self.client.get('/api/v1/admin/platform/restaurants/activation-options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['custom_tariff_allowed'])

    def test_tariff_create_derives_permissions_from_selected_roles(self):
        self.client.force_authenticate(self.product_owner_user)
        response = self.client.post(
            '/api/v1/admin/platform/tariffs/',
            {
                'name': 'Derived Tariff', 'description': 'Derived permissions', 'is_active': True,
                'allowed_role_ids': [str(self.fast_food_admin_role.id), str(self.fast_food_cashier_role.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        permission_codes = {permission['code'] for permission in response.data['permissions']}
        self.assertIn('dashboard.view', permission_codes)
        self.assertIn('pos_takeaway_menu.view', permission_codes)
        self.assertNotIn('monthly_price', response.data)
        self.assertNotIn('yearly_price', response.data)

    def test_tariff_create_allows_manual_permission_selection(self):
        self.client.force_authenticate(self.product_owner_user)
        roles_view = Permission.objects.get(code='roles.view')
        response = self.client.post(
            '/api/v1/admin/platform/tariffs/',
            {
                'name': 'Manual Tariff', 'description': 'Manual permissions', 'is_active': True,
                'allowed_role_ids': [str(self.fast_food_admin_role.id)],
                'permission_ids': [str(roles_view.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            {permission['code'] for permission in response.data['permissions']},
            {'dashboard.view', 'roles.view'},
        )

    def test_product_owner_can_fetch_role_and_permission_options(self):
        self.client.force_authenticate(self.product_owner_user)
        roles_response = self.client.get('/api/v1/admin/roles/', {'pageSize': 100})
        permissions_response = self.client.get('/api/v1/admin/permissions/options/')

        self.assertEqual(roles_response.status_code, status.HTTP_200_OK)
        self.assertEqual(permissions_response.status_code, status.HTTP_200_OK)
        self.assertIn('restaurant_admin', {item['code'] for item in roles_response.data['data']})
        self.assertIn('employees.view', {item['code'] for item in permissions_response.data})

    def test_fast_food_activation_assigns_fast_food_admin_role(self):
        self.client.force_authenticate(self.business_partner_user)
        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {'tariff_id': str(self.fast_food_tariff.id)}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        admin_user = User.objects.get(username=response.data['username'])
        self.assertEqual(admin_user.role.code, 'fast_food_admin')
        self.assertFalse(admin_user.is_staff)
        self.assertFalse(admin_user.is_superuser)
        self.assertTrue(self.restaurant.entitlement.is_active)
        self.assertEqual(self.restaurant.entitlement.tariff_id, self.fast_food_tariff.id)
        self.assertNotIn('billing_period', response.data['restaurant'])
        self.assertNotIn('expires_on', response.data['restaurant'])

        login_response = self.client.post(
            '/api/v1/dashboard/auth/login/',
            {'username': response.data['username'], 'password': response.data['password']},
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)

    def test_reactivation_removes_accidental_django_staff_from_non_superuser(self):
        admin_user = User.objects.create_user(
            username='legacy-staff-admin', password='secret123', full_name='Legacy Staff Admin',
            role=self.fast_food_admin_role, restaurant=self.restaurant,
            is_staff=True, is_superuser=False,
        )
        self.client.force_authenticate(self.business_partner_user)
        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {'tariff_id': str(self.fast_food_tariff.id)}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        admin_user.refresh_from_db()
        self.assertFalse(admin_user.is_staff)

    def test_custom_activation_uses_selected_roles_and_permissions(self):
        self.partner.extra_permissions.add(self.custom_tariff_permission)
        self.client.force_authenticate(self.business_partner_user)
        employees_view = Permission.objects.get(code='employees.view')
        pos_takeaway = Permission.objects.get(code='pos_takeaway_menu.view')
        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {
                'activation_type': 'custom',
                'allowed_role_ids': [str(self.fast_food_admin_role.id), str(self.fast_food_cashier_role.id)],
                'permission_ids': [str(employees_view.id), str(pos_takeaway.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.restaurant.refresh_from_db()
        self.assertTrue(self.restaurant.entitlement.is_custom)
        self.assertIsNone(self.restaurant.entitlement.tariff_id)
        self.assertEqual(
            set(self.restaurant.entitlement.allowed_roles.values_list('code', flat=True)),
            {'fast_food_admin', 'fast_food_cashier'},
        )
        self.assertEqual(response.data['restaurant']['activation_type'], 'custom')
        self.assertNotIn('starts_on', response.data['restaurant'])
        self.assertNotIn('expires_on', response.data['restaurant'])

    def test_custom_activation_requires_custom_tariff_permission(self):
        self.client.force_authenticate(self.business_partner_user)
        employees_view = Permission.objects.get(code='employees.view')
        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {
                'activation_type': 'custom',
                'allowed_role_ids': [str(self.fast_food_admin_role.id)],
                'permission_ids': [str(employees_view.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('activationType', response.data)

    def test_restaurant_list_excludes_removed_subscription_fields(self):
        self.client.force_authenticate(self.business_partner_user)
        self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {'tariff_id': str(self.fast_food_tariff.id)}, format='json',
        )
        response = self.client.get('/api/v1/admin/restaurants/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = next(item for item in response.data['data'] if item['id'] == str(self.restaurant.id))
        self.assertEqual(row['activation_type'], 'tariff')
        self.assertNotIn('billing_period', row)
        self.assertNotIn('starts_on', row)
        self.assertNotIn('expires_on', row)
        self.assertIsNotNone(row['activated_at'])
