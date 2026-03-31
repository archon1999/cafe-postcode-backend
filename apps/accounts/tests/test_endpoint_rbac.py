from types import SimpleNamespace

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework import permissions, status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.accounts.models import Permission, PermissionEndpoint, Role, User
from apps.accounts.signals.seed_default_roles import seed_default_roles_signal
from apps.organizations.models import FeatureConfig, Restaurant, RestaurantEntitlement
from common.api.permissions import EndpointRBACPermission


class EndpointRBACApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='RBAC restaurant')
        FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            owner_dashboard_enabled=True,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
        )
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=cls.restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        cls.hall_view_permission = Permission.objects.get(code='hall.view')
        cls.dashboard_permission = Permission.objects.get(code='dashboard.view')

        cls.hall_view_role = Role.objects.create(
            code='hall_view_only_test',
            name='Hall View Only',
            description='Hall view only role',
            is_system=False,
        )
        cls.hall_view_role.permissions.set([cls.hall_view_permission])

        cls.dashboard_role = Role.objects.create(
            code='dashboard_only_test',
            name='Dashboard Only',
            description='Dashboard only role',
            is_system=False,
        )
        cls.dashboard_role.permissions.set([cls.dashboard_permission])

        cls.no_access_role = Role.objects.create(
            code='no_access_test',
            name='No Access',
            description='No access role',
            is_system=False,
        )

        cls.entitlement.allowed_roles.set([cls.hall_view_role, cls.dashboard_role, cls.no_access_role])

        cls.hall_view_user = User.objects.create_user(
            username='hall-user',
            password='secret123',
            full_name='Hall User',
            restaurant=cls.restaurant,
            role=cls.hall_view_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )
        cls.dashboard_user = User.objects.create_user(
            username='dashboard-user',
            password='secret123',
            full_name='Dashboard User',
            restaurant=cls.restaurant,
            role=cls.dashboard_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )
        cls.no_access_user = User.objects.create_user(
            username='no-access-user',
            password='secret123',
            full_name='No Access User',
            restaurant=cls.restaurant,
            role=cls.no_access_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )
        cls.superuser = User.objects.create_superuser(
            username='superuser-test',
            password='secret123',
            full_name='Superuser Test',
        )

    def test_superuser_can_access_protected_endpoint(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.get('/api/v1/admin/users/permissions/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_method_specific_route_mapping_allows_get_and_blocks_post(self):
        self.client.force_authenticate(self.hall_view_user)

        get_response = self.client.get('/api/v1/admin/floor/halls/')
        post_response = self.client.post('/api/v1/admin/floor/halls/', {}, format='json')

        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_entitlement_can_disable_role_permission(self):
        self.entitlement.permissions.set(Permission.objects.exclude(code='hall.view'))
        self.client.force_authenticate(self.hall_view_user)

        response = self.client.get('/api/v1/pos/halls/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_auth_only_exempt_endpoint_stays_available(self):
        self.client.force_authenticate(self.no_access_user)

        me_response = self.client.get('/api/v1/pos/auth/me/')
        logout_response = self.client.post('/api/v1/admin/auth/logout/', {}, format='json')

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)


class EndpointRBACPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        restaurant = Restaurant.objects.create(name='Unit test restaurant')
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        hall_view_role = Role.objects.create(
            code='endpoint_permission_unit_role',
            name='Endpoint permission unit role',
            description='Endpoint permission unit role',
            is_system=False,
        )
        hall_view_role.permissions.set([Permission.objects.get(code='hall.view')])
        cls.entitlement.allowed_roles.set([hall_view_role])

        cls.user = User.objects.create_user(
            username='endpoint-unit-user',
            password='secret123',
            full_name='Endpoint Unit User',
            restaurant=restaurant,
            role=hall_view_role,
            is_active=True,
        )

    def test_unmapped_endpoint_is_denied_by_default(self):
        request = APIRequestFactory().get('/api/v1/unmapped/')
        request.user = self.user
        request.resolver_match = SimpleNamespace(route='api/v1/unmapped/')
        view = SimpleNamespace(permission_classes=[permissions.IsAuthenticated, EndpointRBACPermission])

        allowed = EndpointRBACPermission().has_permission(request, view)

        self.assertFalse(allowed)

    def test_seed_sync_removes_stale_endpoint_rows(self):
        permission = Permission.objects.get(code='dashboard.view')
        PermissionEndpoint.objects.create(permission=permission, method='GET', url='api/v1/fake/')

        seed_default_roles_signal(sender=django_apps.get_app_config('accounts'))

        self.assertFalse(PermissionEndpoint.objects.filter(method='GET', url='api/v1/fake/').exists())
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission=permission,
                method='GET',
                url='api/v1/dashboard/overview/',
            ).exists()
        )
