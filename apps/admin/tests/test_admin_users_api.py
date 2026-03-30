from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import EmployeeCompensationProfile, EmployeeProfile, Permission, Role, User
from apps.floor.models import Hall
from apps.organizations.models import Branch, Device, Restaurant, RestaurantEntitlement


class AdminUsersApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Users Test Restaurant',
            phone='+998900000100',
            address='Tashkent',
        )
        cls.branch = Branch.objects.create(
            restaurant=cls.restaurant,
            name='Users Test Branch',
            address='Tashkent',
            phone='+998900000101',
            service_fee_percent=10,
            is_default=True,
        )
        cls.primary_hall = Hall.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            level=1,
            name='Main Hall',
        )
        cls.secondary_hall = Hall.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            level=1,
            name='Family Hall',
        )
        permission_codes = ['users.manage', 'constructor.manage', 'hall.view', 'hall.manage']
        cls.permissions = {
            code: Permission.objects.get_or_create(
                code=code,
                defaults={'name': code, 'description': f'{code} permission'},
            )[0]
            for code in permission_codes
        }
        cls.role, _ = Role.objects.get_or_create(
            code='users-test-role',
            defaults={'name': 'Users Test Role', 'description': 'Role for user API tests', 'is_system': False},
        )
        cls.role.permissions.set(cls.permissions.values())
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set(cls.permissions.values())
        cls.entitlement.allowed_roles.set([cls.role])
        cls.admin_user = User.objects.create_user(
            username='users-admin',
            password='secret123',
            full_name='Users Admin',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.role,
            actor_type=User.ActorType.RESTAURANT_ADMIN,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin_user)

    def test_admin_user_create_persists_employee_profile_and_compensation_fields(self):
        response = self.client.post(
            '/api/v1/admin/users/',
            {
                'username': 'new-pos-user',
                'full_name': 'New POS User',
                'phone': '+998901112233',
                'ui_mode': 'pos',
                'is_active': True,
                'role_id': str(self.role.id),
                'branch_id': str(self.branch.id),
                'hall_switch_permission': True,
                'primary_hall_id': str(self.primary_hall.id),
                'allowed_hall_ids': [str(self.primary_hall.id), str(self.secondary_hall.id)],
                'passport_series': 'AA1234567',
                'pnfl': '12345678901234',
                'birth_date': '1997-04-21',
                'employment_status': 'active',
                'salary_type': 'hourly',
                'base_amount': '150000',
                'pin': '1234',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['employment_status'], 'active')
        self.assertEqual(response.data['passport_series'], 'AA1234567')
        self.assertCountEqual(
            [str(hall_id) for hall_id in response.data['allowed_hall_ids']],
            [str(self.primary_hall.id), str(self.secondary_hall.id)],
        )

        user = User.objects.get(username='new-pos-user')
        self.assertTrue(user.check_pin('1234'))
        self.assertEqual(user.employee_profile.passport_series, 'AA1234567')
        self.assertEqual(user.employee_profile.pnfl, '12345678901234')
        self.assertEqual(user.employee_profile.employment_status, EmployeeProfile.EmploymentStatus.ACTIVE)
        self.assertEqual(user.employee_compensation_profile.salary_type, EmployeeCompensationProfile.SalaryType.HOURLY)
        self.assertEqual(float(user.employee_compensation_profile.base_amount), 150000.0)
        self.assertSetEqual(
            set(user.allowed_halls.values_list('id', flat=True)),
            {self.primary_hall.id, self.secondary_hall.id},
        )

    def test_admin_user_list_hides_archived_by_default_and_returns_them_on_filter(self):
        archived_user = User.objects.create_user(
            username='archived-admin-user',
            password='secret123',
            full_name='Archived Admin User',
            restaurant=self.restaurant,
            branch=self.branch,
            role=self.role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=False,
        )
        archived_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.ARCHIVED
        archived_user.employee_profile.save(update_fields=['employment_status'])

        default_response = self.client.get('/api/v1/admin/users/')
        self.assertEqual(default_response.status_code, status.HTTP_200_OK)
        default_usernames = {row['username'] for row in default_response.data['data']}
        self.assertNotIn(archived_user.username, default_usernames)

        archived_response = self.client.get('/api/v1/admin/users/', {'include_archived': 'true'})
        self.assertEqual(archived_response.status_code, status.HTTP_200_OK)
        archived_usernames = {row['username'] for row in archived_response.data['data']}
        self.assertIn(archived_user.username, archived_usernames)

    def test_admin_user_archive_marks_employee_archived_without_hard_delete(self):
        employee = User.objects.create_user(
            username='archive-me',
            password='secret123',
            full_name='Archive Me',
            restaurant=self.restaurant,
            branch=self.branch,
            role=self.role,
            ui_mode=User.UiMode.POS,
            is_active=True,
        )

        response = self.client.patch(
            f'/api/v1/admin/users/{employee.id}/',
            {'employment_status': 'archived'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)
        self.assertEqual(employee.employee_profile.employment_status, EmployeeProfile.EmploymentStatus.ARCHIVED)

    def test_admin_device_create_sets_primary_hall_and_allowed_halls(self):
        response = self.client.post(
            '/api/v1/admin/constructor/devices/',
            {
                'name': 'Waiter Tablet',
                'mode': 'waiter',
                'branch': str(self.branch.id),
                'primary_hall_id': str(self.primary_hall.id),
                'allowed_hall_ids': [str(self.secondary_hall.id)],
                'is_active': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(str(response.data['primary_hall_id']), str(self.primary_hall.id))
        self.assertCountEqual(
            [str(hall_id) for hall_id in response.data['allowed_hall_ids']],
            [str(self.primary_hall.id), str(self.secondary_hall.id)],
        )

        device = Device.objects.get(name='Waiter Tablet')
        self.assertEqual(device.primary_hall_id, self.primary_hall.id)
        self.assertSetEqual(
            set(device.allowed_halls.values_list('id', flat=True)),
            {self.primary_hall.id, self.secondary_hall.id},
        )
