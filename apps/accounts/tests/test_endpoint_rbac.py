from types import SimpleNamespace

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework import permissions, status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.accounts.models import Permission, PermissionEndpoint, Role, User
from apps.accounts.permission_registry import DEFAULT_ROLE_MAP
from apps.accounts.signals.seed_default_roles import seed_default_roles_signal
from apps.organizations.models import FeatureConfig, Restaurant, RestaurantEntitlement
from common.api.permissions import AUTHENTICATED_RBAC_EXEMPT_ENDPOINTS, EndpointRBACPermission


class EndpointRBACApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name="RBAC restaurant")
        FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            owner_dashboard_enabled=True,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
        )
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=cls.restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        cls.hall_list_permission = Permission.objects.get(code="halls.view")
        cls.pos_hall_permission = Permission.objects.get(code="pos_halls.view")
        cls.dashboard_permission = Permission.objects.get(code="dashboard.view")

        cls.hall_list_role = Role.objects.create(
            code="hall_list_only_test",
            name="Hall List Only",
            description="Hall list only role",
            is_system=False,
        )
        cls.hall_list_role.permissions.set([cls.hall_list_permission])

        cls.dashboard_role = Role.objects.create(
            code="dashboard_only_test",
            name="Dashboard Only",
            description="Dashboard only role",
            is_system=False,
        )
        cls.dashboard_role.permissions.set([cls.dashboard_permission])

        cls.pos_hall_role = Role.objects.create(
            code="pos_hall_only_test",
            name="POS Hall Only",
            description="POS hall only role",
            is_system=False,
        )
        cls.pos_hall_role.permissions.set([cls.pos_hall_permission])

        cls.no_access_role = Role.objects.create(
            code="no_access_test",
            name="No Access",
            description="No access role",
            is_system=False,
        )

        cls.entitlement.allowed_roles.set([cls.hall_list_role, cls.pos_hall_role, cls.dashboard_role, cls.no_access_role])

        cls.hall_list_user = User.objects.create_user(
            username="hall-user",
            password="secret123",
            full_name="Hall User",
            restaurant=cls.restaurant,
            role=cls.hall_list_role,
            is_staff=True,
            is_active=True,
        )
        cls.dashboard_user = User.objects.create_user(
            username="dashboard-user",
            password="secret123",
            full_name="Dashboard User",
            restaurant=cls.restaurant,
            role=cls.dashboard_role,
            is_staff=True,
            is_active=True,
        )
        cls.pos_hall_user = User.objects.create_user(
            username="pos-hall-user",
            password="secret123",
            full_name="POS Hall User",
            restaurant=cls.restaurant,
            role=cls.pos_hall_role,
            is_staff=True,
            is_active=True,
        )
        cls.no_access_user = User.objects.create_user(
            username="no-access-user",
            password="secret123",
            full_name="No Access User",
            restaurant=cls.restaurant,
            role=cls.no_access_role,
            is_staff=True,
            is_active=True,
        )
        cls.superuser = User.objects.create_superuser(
            username="superuser-test",
            password="secret123",
            full_name="Superuser Test",
        )

    def test_superuser_can_access_protected_endpoint(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.get("/api/v1/admin/users/permissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_method_specific_route_mapping_allows_get_and_blocks_post(self):
        self.client.force_authenticate(self.hall_list_user)

        get_response = self.client.get("/api/v1/admin/floor/halls/")
        post_response = self.client.post("/api/v1/admin/floor/halls/", {}, format="json")

        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_entitlement_can_disable_role_permission(self):
        self.entitlement.permissions.set(Permission.objects.exclude(code="pos_halls.view"))
        self.client.force_authenticate(self.pos_hall_user)

        response = self.client.get("/api/v1/pos/halls/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_auth_only_exempt_endpoint_stays_available(self):
        self.client.force_authenticate(self.no_access_user)

        me_response = self.client.get("/api/v1/pos/auth/me/")
        logout_response = self.client.post("/api/v1/admin/auth/logout/", {}, format="json")

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)


class EndpointRBACPermissionTests(TestCase):
    EXPECTED_UNREGISTERED_PROTECTED_ENDPOINTS = {
        ("POST", "api/v1/admin/floor/table-sessions/"),
        ("PUT", "api/v1/admin/floor/table-sessions/<uuid:pk>/"),
        ("PATCH", "api/v1/admin/floor/table-sessions/<uuid:pk>/"),
        ("DELETE", "api/v1/admin/floor/table-sessions/<uuid:pk>/"),
    }

    @classmethod
    def setUpTestData(cls):
        restaurant = Restaurant.objects.create(name="Unit test restaurant")
        FeatureConfig.objects.create(
            restaurant=restaurant,
            owner_dashboard_enabled=True,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
        )
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        hall_list_role = Role.objects.create(
            code="endpoint_permission_unit_role",
            name="Endpoint permission unit role",
            description="Endpoint permission unit role",
            is_system=False,
        )
        hall_list_role.permissions.set([Permission.objects.get(code="halls.view")])
        cls.entitlement.allowed_roles.set([hall_list_role])

        cls.user = User.objects.create_user(
            username="endpoint-unit-user",
            password="secret123",
            full_name="Endpoint Unit User",
            restaurant=restaurant,
            role=hall_list_role,
            is_active=True,
        )

    def test_unmapped_endpoint_is_denied_by_default(self):
        request = APIRequestFactory().get("/api/v1/unmapped/")
        request.user = self.user
        request.resolver_match = SimpleNamespace(route="api/v1/unmapped/")
        view = SimpleNamespace(permission_classes=[permissions.IsAuthenticated, EndpointRBACPermission])

        allowed = EndpointRBACPermission().has_permission(request, view)

        self.assertFalse(allowed)

    def test_seed_sync_removes_stale_endpoint_rows(self):
        permission = Permission.objects.get(code="dashboard.view")
        PermissionEndpoint.objects.create(permission=permission, method="GET", url="api/v1/fake/")

        seed_default_roles_signal(sender=django_apps.get_app_config("accounts"))

        self.assertFalse(PermissionEndpoint.objects.filter(method="GET", url="api/v1/fake/").exists())
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission=permission,
                method="GET",
                url="api/v1/dashboard/overview/",
            ).exists()
        )

    def test_removed_permission_codes_are_absent_from_seed(self):
        seed_default_roles_signal(sender=django_apps.get_app_config("accounts"))

        self.assertFalse(Permission.objects.filter(code="order_items.list").exists())
        self.assertFalse(Permission.objects.filter(code="order_item_notes.view").exists())
        self.assertFalse(Permission.objects.filter(code="cash_shifts.view").exists())
        self.assertFalse(Permission.objects.filter(code__endswith=".list").exists())
        self.assertFalse(Permission.objects.filter(code="business_partners.lookup").exists())
        self.assertFalse(Permission.objects.filter(code="mxik.search").exists())
        self.assertFalse(Permission.objects.filter(code="mxik.view").exists())
        self.assertFalse(Permission.objects.filter(code="catalog_menu.view").exists())
        self.assertFalse(Permission.objects.filter(code="open_checks.view").exists())
        self.assertFalse(Permission.objects.filter(code="payments.create").exists())
        self.assertFalse(Permission.objects.filter(code="payments.update").exists())
        self.assertFalse(Permission.objects.filter(code="kitchen_queue.view").exists())
        self.assertFalse(Permission.objects.filter(surface="system").exists())
        self.assertTrue(Permission.objects.filter(code="halls.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_halls.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_tables.manage").exists())
        self.assertTrue(Permission.objects.filter(code="pos_table_menu.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_takeaway_menu.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_kitchen_orders.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_kitchen_orders.update").exists())
        self.assertTrue(Permission.objects.filter(code="pos_open_checks.view").exists())
        self.assertTrue(Permission.objects.filter(code="pos_payments.create").exists())
        self.assertTrue(Permission.objects.filter(code="pos_table_reservations.manage").exists())
        self.assertTrue(Permission.objects.filter(code="reports.view").exists())

    def test_orders_permissions_absorb_order_item_endpoints(self):
        seed_default_roles_signal(sender=django_apps.get_app_config("accounts"))

        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="orders.view",
                method="GET",
                url="api/v1/admin/order-items/",
            ).exists()
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_tables.manage",
                method="GET",
                url="api/v1/pos/orders/<uuid:order_id>/items/",
            ).exists()
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_takeaway_menu.view",
                method="GET",
                url="api/v1/pos/orders/<uuid:order_id>/items/",
            ).exists()
        )

    def test_pos_shared_endpoints_are_mapped_to_multiple_permissions(self):
        seed_default_roles_signal(sender=django_apps.get_app_config("accounts"))

        self.assertEqual(
            PermissionEndpoint.objects.filter(method="GET", url="api/v1/pos/catalog/menu/").count(),
            2,
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_table_menu.view",
                method="GET",
                url="api/v1/pos/catalog/menu/",
            ).exists()
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_takeaway_menu.view",
                method="GET",
                url="api/v1/pos/catalog/menu/",
            ).exists()
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_tables.manage",
                method="POST",
                url="api/v1/pos/orders/",
            ).exists()
        )
        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="pos_takeaway_menu.view",
                method="POST",
                url="api/v1/pos/orders/",
            ).exists()
        )

    def test_reports_view_absorbs_export_endpoints(self):
        seed_default_roles_signal(sender=django_apps.get_app_config("accounts"))

        self.assertTrue(
            PermissionEndpoint.objects.filter(
                permission__code="reports.view",
                method="GET",
                url="api/v1/admin/reports/shifts/export/",
            ).exists()
        )

    def test_default_product_owner_role_is_limited_to_business_partners_and_tariffs(self):
        permission_codes = set(DEFAULT_ROLE_MAP["product_owner"]["permissions"])

        self.assertEqual(
            permission_codes,
            {
                "platform.product_owner.view",
                "tariff_roles.view",
                "tariff_permissions.view",
                "business_partners.view",
                "business_partners.create",
                "business_partners.update",
                "business_partners.activate",
                "business_partners.deactivate",
                "business_partners.reset_password",
                "tariffs.view",
                "tariffs.create",
                "tariffs.update",
            },
        )

    def test_restaurant_admin_defaults_exclude_roles_and_permissions_pages(self):
        permission_codes = set(DEFAULT_ROLE_MAP["restaurant_admin"]["permissions"])

        self.assertNotIn("roles.view", permission_codes)
        self.assertNotIn("permissions.view", permission_codes)

    def test_fast_food_admin_defaults_include_restaurant_management_and_catalog_without_floor(self):
        permission_codes = set(DEFAULT_ROLE_MAP["fast_food_admin"]["permissions"])

        self.assertIn("restaurant_settings.view", permission_codes)
        self.assertIn("cash_desks.view", permission_codes)
        self.assertIn("catalog_items.view", permission_codes)
        self.assertIn("catalog_categories.view", permission_codes)
        self.assertNotIn("halls.view", permission_codes)
        self.assertNotIn("zones.view", permission_codes)
        self.assertNotIn("tables.view", permission_codes)
        self.assertNotIn("table_sessions.view", permission_codes)

    def test_every_protected_route_is_registered_in_permission_endpoints(self):
        missing = []

        for route, view_cls in self._iter_api_view_routes(get_resolver().url_patterns):
            permission_classes = getattr(view_cls, "permission_classes", [])
            if any(issubclass(permission_class, permissions.AllowAny) for permission_class in permission_classes):
                continue

            for method in self._view_methods(view_cls):
                normalized_method = "GET" if method == "HEAD" else method
                if (normalized_method, route) in AUTHENTICATED_RBAC_EXEMPT_ENDPOINTS:
                    continue
                if (normalized_method, route) in self.EXPECTED_UNREGISTERED_PROTECTED_ENDPOINTS:
                    continue
                if not PermissionEndpoint.objects.filter(method=normalized_method, url=route).exists():
                    missing.append(f"{normalized_method} {route}")

        self.assertEqual(missing, [])

    @classmethod
    def _iter_api_view_routes(cls, patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                nested_prefix = prefix + str(pattern.pattern)
                yield from cls._iter_api_view_routes(pattern.url_patterns, nested_prefix)
                continue

            if not isinstance(pattern, URLPattern):
                continue

            route = prefix + str(pattern.pattern)
            callback = pattern.callback
            view_cls = getattr(callback, "cls", None)
            if view_cls is None or not route.startswith("api/v1/"):
                continue
            yield route, view_cls

    @staticmethod
    def _view_methods(view_cls):
        methods = []
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            if hasattr(view_cls, method.lower()):
                methods.append(method)
        return methods

