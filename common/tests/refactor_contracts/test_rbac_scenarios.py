from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from rest_framework import permissions, status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.floor.models import Hall, ZoneOrCabin
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User
from apps.users.permission_registry import DEFAULT_ROLE_MAP
from common.api.permissions import EndpointRBACPermission

from . import normalize_scenario_expected, validate_scenario_v1


def rbac_scenario(scenario_id: str, expected: dict[str, object]) -> dict[str, object]:
    scenario = {
        "schemaVersion": 1,
        "scenarioId": scenario_id,
        "capability": "CAP-RBAC",
        "mode": "remote",
        "actor": {
            "kind": "service",
            "role": "rbac-characterization-observer",
            "restaurantRef": "restaurant:primary",
            "permissionCodes": [],
        },
        "input": {},
        "expected": expected,
        "volatilePaths": [],
        "unorderedCollections": [],
    }
    validate_scenario_v1(scenario)
    return normalize_scenario_expected(scenario)


class BackendRBACCharacterizationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name="RBAC primary restaurant")
        cls.other_restaurant = Restaurant.objects.create(name="RBAC foreign restaurant")
        cls.pos_halls = Permission.objects.get(code="pos_halls.view")
        cls.kitchen_view = Permission.objects.get(code="pos_kitchen_orders.view")
        cls.halls_view = Permission.objects.get(code="halls.view")
        cls.role = Role.objects.create(
            code="rbac_characterization_role",
            name="RBAC characterization role",
            is_system=False,
        )
        cls.role.permissions.set([cls.pos_halls, cls.kitchen_view, cls.halls_view])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
        )
        cls.entitlement.permissions.set(
            [cls.pos_halls, cls.kitchen_view, cls.halls_view]
        )
        cls.entitlement.allowed_roles.set([cls.role])
        cls.user = User.objects.create_user(
            username="rbac-characterization-user",
            password="test-only-password",
            full_name="RBAC Characterization User",
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            username="rbac-characterization-superuser",
            password="test-only-password",
            full_name="RBAC Characterization Superuser",
        )

    def _engine_allows(
        self,
        method: str,
        route: str | None,
        *,
        user=None,
        allow_any: bool = False,
    ) -> bool:
        request = APIRequestFactory().generic(method, f"/{route or ''}")
        request.user = user if user is not None else AnonymousUser()
        request.resolver_match = (
            SimpleNamespace(route=route) if route is not None else None
        )
        permission_classes = [
            permissions.AllowAny if allow_any else permissions.IsAuthenticated,
            EndpointRBACPermission,
        ]
        view = SimpleNamespace(permission_classes=permission_classes)
        return EndpointRBACPermission().has_permission(request, view)

    def test_authoritative_engine_matrix(self):
        route = "api/v1/admin/floor/halls/"
        actual = rbac_scenario(
            "rbac.remote.authoritative-engine",
            {
                "options": self._engine_allows("OPTIONS", route),
                "allowAny": self._engine_allows("GET", route, allow_any=True),
                "unauthenticated": self._engine_allows("GET", route),
                "authenticatedExemption": self._engine_allows(
                    "GET", "api/v1/pos/auth/me/", user=self.user
                ),
                "superuser": self._engine_allows(
                    "GET", route, user=self.superuser
                ),
                "missingRoute": self._engine_allows("GET", None, user=self.user),
                "unmappedRoute": self._engine_allows(
                    "GET", "api/v1/unmapped/", user=self.user
                ),
                "headUsesGetAuthority": self._engine_allows(
                    "HEAD", route, user=self.user
                ),
                "methodMismatch": self._engine_allows(
                    "POST", route, user=self.user
                ),
            },
        )

        self.assertEqual(
            actual,
            {
                "options": True,
                "allowAny": True,
                "unauthenticated": False,
                "authenticatedExemption": True,
                "superuser": True,
                "missingRoute": False,
                "unmappedRoute": False,
                "headUsesGetAuthority": True,
                "methodMismatch": False,
            },
        )

    def test_default_role_authority_matrix(self):
        checks = {
            "waiter": (
                "pos_halls.view",
                "pos_tables.manage",
                "pos_payments.create",
                "pos_table_reservations.manage",
            ),
            "manager": (
                "pos_halls.view",
                "pos_takeaway_menu.view",
                "pos_payments.create",
                "pos_cash_shift.manage",
                "pos_kitchen_orders.view",
            ),
            "cashier": (
                "pos_takeaway_menu.view",
                "pos_open_checks.view",
                "pos_payments.create",
                "pos_halls.view",
                "pos_payment_order_items.create",
            ),
            "fast_food_cashier": (
                "pos_takeaway_menu.view",
                "pos_open_checks.view",
                "pos_payment_order_items.create",
                "pos_payment_order_items.delete",
                "pos_halls.view",
            ),
            "chef": (
                "pos_kitchen_orders.view",
                "pos_kitchen_orders.update",
                "pos_payments.create",
                "pos_kitchen_orders.cancel",
            ),
            "restaurant_admin": (
                "dashboard.view",
                "restaurant_settings.view",
                "catalog_items.view",
                "roles.view",
                "permissions.view",
            ),
        }
        actual = {
            role: {
                code: code in DEFAULT_ROLE_MAP[role]["permissions"]
                for code in permission_codes
            }
            for role, permission_codes in checks.items()
        }

        self.assertEqual(
            rbac_scenario("rbac.remote.default-roles", actual),
            {
                "waiter": {
                    "pos_halls.view": True,
                    "pos_tables.manage": True,
                    "pos_payments.create": False,
                    "pos_table_reservations.manage": False,
                },
                "manager": {
                    "pos_halls.view": True,
                    "pos_takeaway_menu.view": True,
                    "pos_payments.create": True,
                    "pos_cash_shift.manage": True,
                    "pos_kitchen_orders.view": False,
                },
                "cashier": {
                    "pos_takeaway_menu.view": True,
                    "pos_open_checks.view": True,
                    "pos_payments.create": True,
                    "pos_halls.view": True,
                    "pos_payment_order_items.create": False,
                },
                "fast_food_cashier": {
                    "pos_takeaway_menu.view": True,
                    "pos_open_checks.view": True,
                    "pos_payment_order_items.create": True,
                    "pos_payment_order_items.delete": True,
                    "pos_halls.view": False,
                },
                "chef": {
                    "pos_kitchen_orders.view": True,
                    "pos_kitchen_orders.update": True,
                    "pos_payments.create": False,
                    "pos_kitchen_orders.cancel": False,
                },
                "restaurant_admin": {
                    "dashboard.view": True,
                    "restaurant_settings.view": True,
                    "catalog_items.view": True,
                    "roles.view": False,
                    "permissions.view": False,
                },
            },
        )

    def test_entitlement_intersects_role_authority(self):
        self.client.force_authenticate(self.user)
        active = self.client.get("/api/v1/pos/floor/halls/")
        active_codes = self.user.permission_codes
        self.entitlement.permissions.set([self.kitchen_view, self.halls_view])
        disabled = self.client.get("/api/v1/pos/floor/halls/")

        self.assertEqual(
            rbac_scenario(
                "rbac.remote.entitlement-intersection",
                {
                    "active": {
                        "httpStatus": active.status_code,
                        "permissionCodes": active_codes,
                    },
                    "permissionRemoved": {
                        "httpStatus": disabled.status_code,
                        "permissionCodes": self.user.permission_codes,
                    },
                },
            ),
            {
                "active": {
                    "httpStatus": status.HTTP_200_OK,
                    "permissionCodes": [
                        "halls.view",
                        "pos_halls.view",
                        "pos_kitchen_orders.view",
                    ],
                },
                "permissionRemoved": {
                    "httpStatus": status.HTTP_403_FORBIDDEN,
                    "permissionCodes": ["halls.view", "pos_kitchen_orders.view"],
                },
            },
        )

    def test_tenant_read_write_and_explicit_query_boundaries(self):
        local_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant, name="Local zone", sort_order=1
        )
        foreign_zone = ZoneOrCabin.objects.create(
            restaurant=self.other_restaurant, name="Foreign zone", sort_order=1
        )
        local_hall = Hall.objects.create(
            zone_or_cabin=local_zone, name="Local hall", sort_order=1
        )
        Hall.objects.create(
            zone_or_cabin=foreign_zone, name="Foreign hall", sort_order=1
        )
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))
        hall_list = self.client.get("/api/v1/admin/floor/halls/")
        foreign_write = self.client.put(
            f"/api/v1/admin/floor/halls/{local_hall.id}/",
            {
                "name": local_hall.name,
                "gridColumns": local_hall.grid_columns,
                "sortOrder": local_hall.sort_order,
                "isActive": local_hall.is_active,
                "zoneOrCabinId": str(foreign_zone.id),
            },
            format="json",
        )
        self.client.credentials()
        self.client.force_authenticate(self.user)
        foreign_monitor = self.client.get(
            "/api/v1/pos/monitor/kitchen-queue/"
            f"?restaurant_id={self.other_restaurant.id}"
        )

        self.assertEqual(
            rbac_scenario(
                "rbac.remote.tenant-boundaries",
                {
                    "scopedList": {
                        "httpStatus": hall_list.status_code,
                        "names": [row["name"] for row in hall_list.data["data"]],
                    },
                    "foreignReferenceWrite": {
                        "httpStatus": foreign_write.status_code,
                        "errorFields": sorted(foreign_write.data),
                    },
                    "foreignExplicitQuery": {
                        "httpStatus": foreign_monitor.status_code,
                    },
                },
            ),
            {
                "scopedList": {"httpStatus": 200, "names": ["Local hall"]},
                "foreignReferenceWrite": {
                    "httpStatus": 400,
                    "errorFields": ["zoneOrCabinId"],
                },
                "foreignExplicitQuery": {"httpStatus": 403},
            },
        )
