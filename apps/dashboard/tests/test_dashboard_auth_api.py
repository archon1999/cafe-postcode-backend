from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.organizations.models import FeatureConfig, Restaurant, RestaurantEntitlement


class DashboardAuthApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name="Test restaurant")
        FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            owner_dashboard_enabled=True,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
        )
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=cls.restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        cls.dashboard_permission = Permission.objects.get(code="dashboard.view")
        cls.hall_permission = Permission.objects.get(code="halls.list")

        cls.owner_role = Role.objects.create(
            code="dashboard_owner_test",
            name="Dashboard owner",
            description="Dashboard owner",
            is_system=False,
        )
        cls.owner_role.permissions.set([cls.dashboard_permission])

        cls.staff_role = Role.objects.create(
            code="dashboard_staff_test",
            name="Dashboard staff",
            description="Dashboard staff",
            is_system=False,
        )
        cls.staff_role.permissions.set([cls.hall_permission])

        cls.entitlement.allowed_roles.set([cls.owner_role, cls.staff_role])

        cls.owner_user = User.objects.create_user(
            username="owner-user",
            password="secret123",
            full_name="Owner User",
            restaurant=cls.restaurant,
            role=cls.owner_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )
        cls.staff_user = User.objects.create_user(
            username="staff-user",
            password="secret123",
            full_name="Staff User",
            restaurant=cls.restaurant,
            role=cls.staff_role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
            is_active=True,
        )

    def test_dashboard_auth_me_requires_dashboard_permission(self):
        self.client.force_authenticate(self.owner_user)
        owner_response = self.client.get("/api/v1/dashboard/auth/me/")
        self.assertEqual(owner_response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.staff_user)
        staff_response = self.client.get("/api/v1/dashboard/auth/me/")
        self.assertEqual(staff_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_overview_requires_dashboard_permission(self):
        self.client.force_authenticate(self.staff_user)
        response = self.client.get("/api/v1/dashboard/overview/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_overview_requires_owner_dashboard_feature(self):
        self.client.force_authenticate(self.owner_user)
        feature_config = self.restaurant.feature_config
        feature_config.owner_dashboard_enabled = False
        feature_config.save(update_fields=["owner_dashboard_enabled", "updated_at"])

        response = self.client.get("/api/v1/dashboard/overview/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
