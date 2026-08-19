from uuid import uuid4

from rest_framework import status
from rest_framework.test import APITestCase

from apps.devices.models import SecurityEvent
from apps.platform.models import BusinessPartner, RestaurantEntitlement, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


class TenantSystemEndpointIsolationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name="Tenant restaurant")
        cls.other_restaurant = Restaurant.objects.create(name="Foreign restaurant")
        cls.role = Role.objects.create(
            code="tenant-overprivileged-test",
            name="Tenant overprivileged test",
            is_system=False,
        )
        cls.role.permissions.set(Permission.objects.all())
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set(Permission.objects.all())
        cls.entitlement.allowed_roles.set([cls.role])
        cls.user = User.objects.create_user(
            username="tenant-overprivileged",
            password="secret123",
            full_name="Tenant Overprivileged",
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.tariff = Tariff.objects.create(
            name="Protected tariff",
            is_active=True,
        )
        cls.partner = BusinessPartner.objects.create(
            inn="123456789",
            company_name="Protected partner",
            legal_name="Protected partner",
        )

    def setUp(self):
        self.client.force_authenticate(self.user)

    def assert_scope_denied(self, method, path, data=None):
        response = getattr(self.client, method)(path, data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        return response

    def test_tenant_account_cannot_enter_global_user_role_or_permission_surfaces(self):
        before_users = User.objects.count()
        before_roles = Role.objects.count()

        for path in (
            "/api/v1/admin/users/",
            "/api/v1/admin/roles/",
            "/api/v1/admin/permissions/",
            "/api/v1/admin/permissions/options/",
        ):
            self.assert_scope_denied("get", path)

        self.assert_scope_denied(
            "post",
            "/api/v1/admin/users/",
            {
                "username": "escaped-platform-user",
                "fullName": "Escaped Platform User",
                "roleId": str(self.role.id),
                "password": "UnsafePassword123!",
            },
        )
        self.assert_scope_denied(
            "post",
            "/api/v1/admin/roles/",
            {"name": "Injected global role", "permissionIds": []},
        )

        self.assertEqual(User.objects.count(), before_users)
        self.assertEqual(Role.objects.count(), before_roles)
        self.assertGreaterEqual(
            SecurityEvent.objects.filter(
                restaurant=self.restaurant,
                actor=self.user,
                event_type="TENANT_SYSTEM_SCOPE_DENIED",
                result="denied",
            ).count(),
            6,
        )

    def test_tenant_account_cannot_mutate_platform_resources_even_with_permissions(self):
        before_restaurants = Restaurant.objects.count()
        before_tariffs = Tariff.objects.count()

        self.assert_scope_denied("get", "/api/v1/admin/platform/tariffs/")
        self.assert_scope_denied(
            "post",
            "/api/v1/admin/platform/tariffs/",
            {
                "name": "Injected tariff",
                "monthlyPrice": 1,
                "yearlyPrice": 1,
                "permissionIds": [],
                "allowedRoleIds": [],
            },
        )
        self.assert_scope_denied("get", "/api/v1/admin/platform/business-partners/")
        self.assert_scope_denied(
            "post",
            f"/api/v1/admin/platform/restaurants/{self.restaurant.id}/activate/",
            {
                "activationType": "custom",
                "billingPeriod": "monthly",
                "startsOn": "2026-08-16",
                "allowedRoleIds": [str(self.role.id)],
                "permissionIds": list(Permission.objects.values_list("id", flat=True)),
            },
        )
        self.assert_scope_denied(
            "post",
            "/api/v1/admin/restaurants/",
            {"name": "Injected restaurant", "isActive": True},
        )

        self.assertEqual(Restaurant.objects.count(), before_restaurants)
        self.assertEqual(Tariff.objects.count(), before_tariffs)
        self.assertGreaterEqual(
            SecurityEvent.objects.filter(
                restaurant=self.restaurant,
                actor=self.user,
                event_type="TENANT_PLATFORM_SCOPE_DENIED",
                result="denied",
            ).count(),
            5,
        )

    def test_foreign_and_unknown_platform_resource_paths_are_indistinguishable(self):
        foreign = self.assert_scope_denied(
            "get", f"/api/v1/admin/restaurants/{self.other_restaurant.id}/"
        )
        unknown = self.assert_scope_denied(
            "get", f"/api/v1/admin/restaurants/{uuid4()}/"
        )

        self.assertEqual(foreign.data, unknown.data)
