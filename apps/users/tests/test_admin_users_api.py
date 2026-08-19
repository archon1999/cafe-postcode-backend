from uuid import uuid4

from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.floor.models import Hall, ZoneOrCabin
from apps.restaurants.models import Restaurant
from apps.platform.models import RestaurantEntitlement, Tariff


class AdminUsersApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Users Test Restaurant',
            phone='+998900000100',
            address='Tashkent',
            is_active=True,
        )
        cls.zone = ZoneOrCabin.objects.create(
            restaurant=cls.restaurant,
            name='Main zone',
            sort_order=1,
            is_active=True,
        )
        cls.primary_hall = Hall.objects.create(
            zone_or_cabin=cls.zone,
            name='Main Hall',
            sort_order=1,
            is_active=True,
        )
        cls.secondary_hall = Hall.objects.create(
            zone_or_cabin=cls.zone,
            name='Family Hall',
            sort_order=2,
            is_active=True,
        )

        cls.restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        cls.waiter_role = Role.objects.get(code='waiter')
        cls.cashier_role = Role.objects.get(code='cashier')
        cls.fast_food_cashier_role = Role.objects.get(code='fast_food_cashier')

        cls.tariff = Tariff.objects.create(
            name='Users Test Tariff',
            description='Users API test tariff',
            is_active=True,
        )
        cls.tariff.allowed_roles.set([cls.restaurant_admin_role, cls.waiter_role, cls.cashier_role])
        cls.tariff.permissions.set(
            {
                *cls.restaurant_admin_role.permissions.values_list('id', flat=True),
                *cls.waiter_role.permissions.values_list('id', flat=True),
                *cls.cashier_role.permissions.values_list('id', flat=True),
            }
        )

        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            tariff=cls.tariff,
            is_active=True,
            is_custom=False,
        )

        cls.admin_user = User.objects.create_user(
            username='users-admin',
            password='secret123',
            full_name='Users Admin',
            restaurant=cls.restaurant,
            role=cls.restaurant_admin_role,
            is_staff=True,
            is_active=True,
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin_user)

    def test_employee_roles_endpoint_returns_only_pos_roles_from_tariff(self):
        response = self.client.get('/api/v1/admin/employees/roles/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        role_codes = {item['code'] for item in response.data['data']}
        self.assertIn('waiter', role_codes)
        self.assertIn('cashier', role_codes)
        self.assertIn('restaurant_admin', role_codes)
        self.assertNotIn('fast_food_cashier', role_codes)
        self.assertNotIn('fast_food_admin', role_codes)

    def test_employee_create_rejects_role_outside_tariff(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Fast Food Cashier',
                'phone': '+998901112233',
                'is_active': True,
                'role_id': str(self.fast_food_cashier_role.id),
                'employment_status': 'active',
                'pin': '1234',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('roleId', response.data)

    def test_employee_create_requires_credentials_for_admin_role(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Restaurant Admin Clone',
                'phone': '+998901112244',
                'is_active': True,
                'role_id': str(self.restaurant_admin_role.id),
                'employment_status': 'active',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', response.data)
        self.assertIn('password', response.data)

    def test_employee_create_accepts_admin_role_with_login_credentials(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Restaurant Admin Clone',
                'phone': '+998901112244',
                'is_active': True,
                'role_id': str(self.restaurant_admin_role.id),
                'employment_status': 'active',
                'username': 'restaurant-admin-clone',
                'password': 'Secret123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['username'], 'restaurant-admin-clone')

        employee = User.objects.get(pk=response.data['id'])
        self.assertEqual(employee.role_id, self.restaurant_admin_role.id)
        self.assertTrue(employee.check_password('Secret123!'))
        self.assertEqual(employee.restaurant_profile.restaurant_id, self.restaurant.id)
        self.assertEqual(employee.restaurant_profile.pin_code, '')
        self.assertIn('dashboard.view', employee.permission_codes)

        list_response = self.client.get('/api/v1/admin/employees/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        listed_ids = {item['id'] for item in list_response.data['data']}
        self.assertIn(str(employee.id), listed_ids)

        detail_response = self.client.get(f'/api/v1/admin/employees/{employee.id}/')
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['username'], 'restaurant-admin-clone')

    def test_superuser_without_restaurant_header_lists_employees_from_all_branches(self):
        other_restaurant = Restaurant.objects.create(name='Other Users Test Restaurant')
        first_employee = User.objects.create_user(
            username='first-branch-waiter',
            full_name='First Branch Waiter',
            restaurant=self.restaurant,
            role=self.waiter_role,
        )
        second_employee = User.objects.create_user(
            username='second-branch-waiter',
            full_name='Second Branch Waiter',
            restaurant=other_restaurant,
            role=self.waiter_role,
        )
        superuser = User.objects.create_superuser(username='all-branches-superuser', password='secret123')
        self.client.force_authenticate(superuser)

        response = self.client.get('/api/v1/admin/employees/?pageSize=100')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        employees_by_id = {item['id']: item for item in response.data['data']}
        self.assertIn(str(first_employee.id), employees_by_id)
        self.assertIn(str(second_employee.id), employees_by_id)
        self.assertEqual(employees_by_id[str(first_employee.id)]['restaurant_name'], self.restaurant.name)
        self.assertEqual(employees_by_id[str(second_employee.id)]['restaurant_name'], other_restaurant.name)

    def test_employee_create_persists_pin_and_hall_assignments_for_waiter(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'New Waiter',
                'phone': '+998901112255',
                'is_active': True,
                'role_id': str(self.waiter_role.id),
                'employment_status': 'active',
                'primary_hall_id': str(self.primary_hall.id),
                'allowed_hall_ids': [str(self.primary_hall.id), str(self.secondary_hall.id)],
                'hall_switch_permission': True,
                'pin': '1234',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['employment_status'], 'active')
        self.assertEqual(str(response.data['primary_hall_id']), str(self.primary_hall.id))
        self.assertCountEqual(
            [str(hall_id) for hall_id in response.data['allowed_hall_ids']],
            [str(self.primary_hall.id), str(self.secondary_hall.id)],
        )
        self.assertTrue(response.data['username'].startswith('users-test-restaurant-new-waiter'))

        employee = User.objects.get(pk=response.data['id'])
        self.assertTrue(employee.check_pin('1234'))
        self.assertFalse(employee.has_usable_password())
        self.assertEqual(employee.restaurant_profile.primary_hall_id, self.primary_hall.id)
        self.assertSetEqual(
            set(employee.restaurant_profile.allowed_halls.values_list('id', flat=True)),
            {self.primary_hall.id, self.secondary_hall.id},
        )

    def test_employee_create_accepts_monthly_salary_with_optional_kpi(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Monthly Waiter',
                'phone': '+998901112266',
                'is_active': True,
                'role_id': str(self.waiter_role.id),
                'employment_status': 'active',
                'salary_type': 'monthly',
                'base_amount': '0',
                'pin': '2233',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        employee = User.objects.get(pk=response.data['id'])
        self.assertEqual(employee.employee_profile.salary_type, 'monthly')
        self.assertEqual(float(employee.employee_profile.base_amount), 0.0)
        self.assertIsNone(employee.employee_profile.kpi_percent)

    def test_employee_create_accepts_independent_kpi_percent(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'KPI Waiter',
                'phone': '+998901112277',
                'is_active': True,
                'role_id': str(self.waiter_role.id),
                'employment_status': 'active',
                'salary_type': 'daily',
                'base_amount': '120000',
                'kpi_percent': 15,
                'pin': '3344',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        employee = User.objects.get(pk=response.data['id'])
        self.assertEqual(employee.employee_profile.kpi_percent, 15)

    def test_employee_create_rejects_negative_kpi_percent(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Negative KPI Waiter',
                'phone': '+998901112288',
                'is_active': True,
                'role_id': str(self.waiter_role.id),
                'employment_status': 'active',
                'salary_type': 'daily',
                'base_amount': '120000',
                'kpi_percent': -1,
                'pin': '4455',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('kpiPercent', response.data)

    def test_employee_create_rejects_negative_base_amount(self):
        response = self.client.post(
            '/api/v1/admin/employees/',
            {
                'full_name': 'Negative Salary Waiter',
                'phone': '+998901112299',
                'is_active': True,
                'role_id': str(self.waiter_role.id),
                'employment_status': 'active',
                'salary_type': 'hourly',
                'base_amount': '-1000',
                'pin': '5566',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('baseAmount', response.data)

    def test_employee_detail_does_not_reveal_another_restaurant_employee(self):
        other_restaurant = Restaurant.objects.create(name='Other employee tenant')
        other_employee = User.objects.create_user(
            username='other-tenant-waiter',
            full_name='Other Tenant Waiter',
            restaurant=other_restaurant,
            role=self.waiter_role,
        )

        foreign_response = self.client.get(
            f'/api/v1/admin/employees/{other_employee.id}/',
        )
        unknown_response = self.client.get(
            f'/api/v1/admin/employees/{uuid4()}/',
        )

        self.assertEqual(foreign_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unknown_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign_response.data, unknown_response.data)

    def test_employee_create_rejects_foreign_and_unknown_hall_ids(self):
        other_restaurant = Restaurant.objects.create(name='Other hall tenant')
        other_zone = ZoneOrCabin.objects.create(
            restaurant=other_restaurant,
            name='Other tenant zone',
        )
        other_hall = Hall.objects.create(
            zone_or_cabin=other_zone,
            name='Other tenant hall',
        )
        user_count = User.objects.count()
        base_payload = {
            'full_name': 'Scoped Waiter',
            'phone': '+998901110000',
            'is_active': True,
            'role_id': str(self.waiter_role.id),
            'employment_status': 'active',
            'pin': '7788',
        }

        foreign_response = self.client.post(
            '/api/v1/admin/employees/',
            {
                **base_payload,
                'primary_hall_id': str(other_hall.id),
            },
            format='json',
        )
        unknown_response = self.client.post(
            '/api/v1/admin/employees/',
            {
                **base_payload,
                'primary_hall_id': str(uuid4()),
            },
            format='json',
        )

        self.assertEqual(foreign_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('primaryHallId', foreign_response.data)
        self.assertIn('primaryHallId', unknown_response.data)
        self.assertEqual(User.objects.count(), user_count)

    def test_employee_role_assignment_cannot_exceed_actor_permissions(self):
        employee_update_permission = Permission.objects.get(code='employees.update')
        delegated_role = Role.objects.create(
            code='delegated-employee-editor',
            name='Delegated employee editor',
            is_system=False,
        )
        delegated_role.permissions.set([employee_update_permission])
        self.entitlement.allowed_roles.add(delegated_role)
        delegated_user = User.objects.create_user(
            username='delegated-employee-editor',
            password='secret123',
            full_name='Delegated Employee Editor',
            restaurant=self.restaurant,
            role=delegated_role,
            is_staff=True,
        )
        target_user = User.objects.create_user(
            username='role-escalation-target',
            full_name='Role Escalation Target',
            restaurant=self.restaurant,
            role=self.waiter_role,
        )
        self.client.force_authenticate(delegated_user)

        response = self.client.patch(
            f'/api/v1/admin/employees/{target_user.id}/',
            {
                'role_id': str(self.restaurant_admin_role.id),
                'password': 'Secret123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('roleId', response.data)
        target_user.refresh_from_db()
        self.assertEqual(target_user.role_id, self.waiter_role.id)
        self.assertFalse(target_user.check_password('Secret123!'))

