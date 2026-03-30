from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.organizations.models import Branch, FeatureConfig, Restaurant


class DashboardAuthApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.branch = Branch.objects.create(restaurant=cls.restaurant, name='Main', is_default=True)
        cls.owner_role = Role.objects.get_or_create(
            code='owner',
            defaults={'name': 'Owner', 'description': 'Owner role', 'is_system': False},
        )[0]
        dashboard_permission = Permission.objects.get_or_create(
            code='dashboard.view',
            defaults={'name': 'Dashboard view', 'description': 'Dashboard view permission'},
        )[0]
        cls.owner_role.permissions.set([dashboard_permission])
        cls.owner_user = User.objects.create_user(
            username='owner-user',
            password='secret123',
            full_name='Owner User',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.owner_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
        )
        cls.manager_role = Role.objects.get_or_create(
            code='dashboard-manager',
            defaults={'name': 'Manager', 'description': 'Manager role', 'is_system': False},
        )[0]
        cls.manager_role.permissions.set([dashboard_permission])
        cls.manager_user = User.objects.create_user(
            username='manager-user',
            password='secret123',
            full_name='Manager User',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.manager_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
        )
        cls.feature_config = FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            owner_dashboard_enabled=True,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
        )

    def test_owner_dashboard_login_returns_session_metadata(self):
        response = self.client.post(
            '/api/v1/dashboard/auth/login/',
            {'username': self.owner_user.username, 'password': 'secret123'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertIn('session', response.data)
        self.assertEqual(response.data['session']['ui_channel'], 'dashboard')

    def test_non_owner_dashboard_login_is_rejected(self):
        response = self.client.post(
            '/api/v1/dashboard/auth/login/',
            {'username': self.manager_user.username, 'password': 'secret123'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dashboard_overview_requires_owner_dashboard_feature(self):
        self.client.force_authenticate(self.owner_user)
        self.feature_config.owner_dashboard_enabled = False
        self.feature_config.save(update_fields=['owner_dashboard_enabled', 'updated_at'])

        response = self.client.get('/api/v1/dashboard/overview/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
