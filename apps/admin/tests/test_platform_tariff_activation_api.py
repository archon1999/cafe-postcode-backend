from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.organizations.models import BusinessPartner, Restaurant, Tariff


class PlatformTariffActivationApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product_owner_role = Role.objects.get(code='product_owner')
        cls.business_partner_role = Role.objects.get(code='business_partner')
        cls.restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        cls.fast_food_admin_role = Role.objects.get(code='fast_food_admin')
        cls.waiter_role = Role.objects.get(code='waiter')
        cls.fast_food_cashier_role = Role.objects.get(code='fast_food_cashier')

        cls.product_owner_user = User.objects.create_user(
            username='platform-owner',
            password='secret123',
            full_name='Platform Owner',
            role=cls.product_owner_role,
            actor_type=User.ActorType.PRODUCT_OWNER,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )

        cls.partner = BusinessPartner.objects.create(
            inn='123456789',
            company_name='Partner LLC',
            legal_name='Partner LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.business_partner_user = User.objects.create_user(
            username='partner-owner',
            password='secret123',
            full_name='Partner Owner',
            role=cls.business_partner_role,
            actor_type=User.ActorType.BUSINESS_PARTNER,
            business_partner=cls.partner,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )

        cls.restaurant_tariff = Tariff.objects.create(
            name='API Restaurant Tariff',
            description='Restaurant tariff',
            monthly_price=1000,
            yearly_price=10000,
            is_active=True,
        )
        cls.restaurant_tariff.allowed_roles.set([cls.restaurant_admin_role, cls.waiter_role])
        cls.restaurant_tariff.permissions.set(
            {
                *cls.restaurant_admin_role.permissions.values_list('id', flat=True),
                *cls.waiter_role.permissions.values_list('id', flat=True),
            }
        )

        cls.fast_food_tariff = Tariff.objects.create(
            name='API Fast Food Tariff',
            description='Fast food tariff',
            monthly_price=500,
            yearly_price=5000,
            is_active=True,
        )
        cls.fast_food_tariff.allowed_roles.set([cls.fast_food_admin_role, cls.fast_food_cashier_role])
        cls.fast_food_tariff.permissions.set(
            {
                *cls.fast_food_admin_role.permissions.values_list('id', flat=True),
                *cls.fast_food_cashier_role.permissions.values_list('id', flat=True),
            }
        )

        cls.inactive_tariff = Tariff.objects.create(
            name='Inactive Tariff',
            description='Inactive',
            monthly_price=1,
            yearly_price=10,
            is_active=False,
        )

        cls.restaurant = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Activation Restaurant',
            legal_name='Activation Restaurant LLC',
            phone='+998900000001',
            address='Tashkent',
            is_active=False,
        )

    def test_business_partner_can_fetch_only_active_tariff_options(self):
        self.client.force_authenticate(self.business_partner_user)

        response = self.client.get('/api/v1/admin/platform/tariff-options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tariff_names = {item['name'] for item in response.data}
        self.assertIn(self.restaurant_tariff.name, tariff_names)
        self.assertIn(self.fast_food_tariff.name, tariff_names)
        self.assertNotIn(self.inactive_tariff.name, tariff_names)

    def test_business_partner_can_fetch_activation_options(self):
        self.client.force_authenticate(self.business_partner_user)

        response = self.client.get('/api/v1/admin/platform/restaurants/activation-options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({item['name'] for item in response.data['tariffs']}, {self.fast_food_tariff.name, self.restaurant_tariff.name})
        returned_role_codes = {item['code'] for item in response.data['roles']}
        self.assertIn('restaurant_admin', returned_role_codes)
        self.assertIn('fast_food_admin', returned_role_codes)
        self.assertNotIn('product_owner', returned_role_codes)
        self.assertNotIn('business_partner', returned_role_codes)
        returned_permission_codes = {item['code'] for item in response.data['permissions']}
        self.assertIn('employees.view', returned_permission_codes)
        self.assertIn('pos_takeaway_menu.view', returned_permission_codes)
        self.assertNotIn('platform.product_owner.view', returned_permission_codes)

    def test_tariff_create_derives_permissions_from_selected_roles(self):
        self.client.force_authenticate(self.product_owner_user)

        response = self.client.post(
            '/api/v1/admin/platform/tariffs/',
            {
                'name': 'Derived Tariff',
                'description': 'Derived permissions',
                'monthly_price': '100',
                'yearly_price': '1000',
                'is_active': True,
                'allowed_role_ids': [str(self.fast_food_admin_role.id), str(self.fast_food_cashier_role.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        permission_codes = {permission['code'] for permission in response.data['permissions']}
        self.assertTrue({'employees.view', 'orders.view', 'restaurant_settings.view', 'catalog_items.view'}.issubset(permission_codes))
        self.assertIn('pos_takeaway_menu.view', permission_codes)
        self.assertNotIn('halls.view', permission_codes)
        self.assertNotIn('tables.view', permission_codes)
        self.assertNotIn('table_sessions.view', permission_codes)

    def test_tariff_create_allows_manual_permission_selection(self):
        self.client.force_authenticate(self.product_owner_user)
        roles_view_permission = Permission.objects.get(code='roles.view')

        response = self.client.post(
            '/api/v1/admin/platform/tariffs/',
            {
                'name': 'Manual Tariff',
                'description': 'Manual permissions',
                'monthly_price': '150',
                'yearly_price': '1500',
                'is_active': True,
                'allowed_role_ids': [str(self.fast_food_admin_role.id)],
                'permission_ids': [str(roles_view_permission.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        permission_codes = {permission['code'] for permission in response.data['permissions']}
        self.assertEqual(permission_codes, {'roles.view'})

    def test_product_owner_can_fetch_role_options_for_tariff_form(self):
        self.client.force_authenticate(self.product_owner_user)

        response = self.client.get('/api/v1/admin/users/roles/', {'pageSize': 100})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data['data'], list)
        returned_role_codes = {item['code'] for item in response.data['data']}
        self.assertIn('restaurant_admin', returned_role_codes)

    def test_product_owner_can_fetch_permission_options_for_tariff_form(self):
        self.client.force_authenticate(self.product_owner_user)

        response = self.client.get('/api/v1/admin/users/permissions/options/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_permission_codes = {item['code'] for item in response.data}
        self.assertIn('employees.view', returned_permission_codes)

    def test_fast_food_activation_assigns_fast_food_admin_role(self):
        self.client.force_authenticate(self.business_partner_user)

        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {
                'tariff_id': str(self.fast_food_tariff.id),
                'starts_on': '2026-04-04',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        admin_user = User.objects.get(username=response.data['username'])
        self.assertEqual(admin_user.role.code, 'fast_food_admin')
        self.assertTrue(self.restaurant.entitlement.is_active)
        self.assertEqual(self.restaurant.entitlement.tariff_id, self.fast_food_tariff.id)

    def test_custom_activation_uses_selected_roles_and_permissions(self):
        self.client.force_authenticate(self.business_partner_user)
        employees_view_permission = Permission.objects.get(code='employees.view')
        pos_takeaway_menu_view_permission = Permission.objects.get(code='pos_takeaway_menu.view')

        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/',
            {
                'activation_type': 'custom',
                'allowed_role_ids': [str(self.fast_food_admin_role.id), str(self.fast_food_cashier_role.id)],
                'permission_ids': [str(employees_view_permission.id), str(pos_takeaway_menu_view_permission.id)],
                'starts_on': '2026-04-04',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.restaurant.refresh_from_db()
        self.assertTrue(self.restaurant.entitlement.is_active)
        self.assertTrue(self.restaurant.entitlement.is_custom)
        self.assertIsNone(self.restaurant.entitlement.tariff_id)
        self.assertEqual(
            set(self.restaurant.entitlement.allowed_roles.values_list('code', flat=True)),
            {'fast_food_admin', 'fast_food_cashier'},
        )
        self.assertEqual(
            set(self.restaurant.entitlement.permissions.values_list('code', flat=True)),
            {'employees.view', 'pos_takeaway_menu.view'},
        )
        admin_user = User.objects.get(username=response.data['username'])
        self.assertEqual(admin_user.role.code, 'fast_food_admin')
        self.assertEqual(set(self.restaurant.feature_config.enabled_roles), {'fast_food_admin', 'fast_food_cashier'})
