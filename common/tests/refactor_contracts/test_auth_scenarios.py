from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.sales.tests.support.pos_api import PosTestDataMixin
from apps.users.models import AuthSession, EmployeeProfile, User
from apps.users.services import AuthSessionService

from .scenarios import (
    auth_scenario,
    canonical_error,
    canonical_pin_session,
    canonical_restaurant,
)


class RemotePosAuthCharacterizationTests(PosTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.set_pin("1111")
        cls.user.save(update_fields=["pin_code"])
        cls.inactive_user = cls._employee(
            "inactive-characterization", "2222", is_active=False
        )
        cls.inactive_user.employee_profile.employment_status = (
            EmployeeProfile.EmploymentStatus.INACTIVE
        )
        cls.inactive_user.employee_profile.save(update_fields=["employment_status"])
        cls.archived_user = cls._employee(
            "archived-characterization", "3333", is_active=False
        )
        cls.archived_user.employee_profile.employment_status = (
            EmployeeProfile.EmploymentStatus.ARCHIVED
        )
        cls.archived_user.employee_profile.save(update_fields=["employment_status"])

    @classmethod
    def _employee(
        cls, username: str, pin: str, *, is_active: bool = True, restaurant=None
    ):
        user = User.objects.create_user(
            username=username,
            password="test-only-password",
            full_name=username.replace("-", " ").title(),
            restaurant=restaurant or cls.restaurant,
            role=cls.role,
            is_active=is_active,
        )
        user.set_pin(pin)
        user.save(update_fields=["pin_code"])
        return user

    def _post_pin(self, restaurant, pin: str, *, ip: str = "192.0.2.41"):
        return self.client.post(
            "/api/v1/pos/auth/pin-login/",
            {"restaurant_id": str(restaurant.id), "pin": pin},
            format="json",
            REMOTE_ADDR=ip,
            HTTP_USER_AGENT="Canonical POS Test",
        )

    def _refs(self, *, users=None, restaurants=None):
        return {
            "user_refs": {
                str(user.id): ref
                for user, ref in (users or [(self.user, "user:primary")])
            },
            "role_refs": {str(self.role.id): "role:pos-test"},
            "restaurant_refs": {
                str(restaurant.id): ref
                for restaurant, ref in (
                    restaurants or [(self.restaurant, "restaurant:primary")]
                )
            },
            "tariff_refs": {str(self.tariff.id): "tariff:pos-test"},
        }

    def test_restaurant_code_selects_only_the_intended_restaurant(self):
        response = self.client.post(
            "/api/v1/pos/auth/restaurant-code/",
            {"code": self.restaurant.auth_code},
            format="json",
        )
        actual = auth_scenario(
            "auth.remote.restaurant-code.valid",
            canonical_restaurant(
                response.status_code,
                response.data,
                restaurant_refs={str(self.restaurant.id): "restaurant:primary"},
            ),
        )

        self.assertEqual(
            actual,
            {
                "httpStatus": 200,
                "restaurantRef": "restaurant:primary",
                "restaurantName": "Test restaurant",
                "backgroundUrl": None,
                "serviceFeeEnabled": True,
                "serviceFeePercent": "10.00",
                "vatEnabled": False,
                "vatPercent": "12.00",
                "markingCheckEnabled": False,
            },
        )

    def test_restaurant_code_denials_preserve_status_field_and_message(self):
        inactive = Restaurant.objects.create(
            name="Inactive auth restaurant", is_active=False
        )
        cases = [
            (
                "not-found",
                {"code": "ZZZZZZ"},
                400,
                {"code": ["Restaurant code is invalid."]},
            ),
            (
                "inactive",
                {"code": inactive.auth_code},
                400,
                {"code": ["Restaurant code is invalid."]},
            ),
            (
                "too-short",
                {"code": "SHORT"},
                400,
                {"code": ["Ensure this field has at least 6 characters."]},
            ),
            (
                "too-long",
                {"code": "TOOLONG"},
                400,
                {"code": ["Ensure this field has no more than 6 characters."]},
            ),
        ]
        for case_id, payload, http_status, body in cases:
            with self.subTest(case=case_id):
                response = self.client.post(
                    "/api/v1/pos/auth/restaurant-code/", payload, format="json"
                )
                actual = auth_scenario(
                    f"auth.remote.restaurant-code.{case_id}",
                    canonical_error(response.status_code, response.data),
                )
                self.assertEqual(actual, {"httpStatus": http_status, "body": body})

    def test_successful_pin_login_preserves_authority_and_session_contract(self):
        response = self._post_pin(self.restaurant, "1111")
        actual = auth_scenario(
            "auth.remote.pin.success",
            canonical_pin_session(response.status_code, response.data, **self._refs()),
            volatile_paths=[{"path": "/session/id", "kind": "uuid"}],
        )

        self.assertEqual(actual["httpStatus"], 200)
        self.assertTrue(actual["tokenPresent"])
        self.assertEqual(actual["user"]["userRef"], "user:primary")
        self.assertEqual(
            actual["user"]["permissionCodes"], sorted(self.permission_codes)
        )
        self.assertEqual(
            actual["session"],
            {
                "id": "<uuid:1>",
                "status": "active",
                "surface": "pos",
                "ttlSeconds": 86400,
                "clientIp": "192.0.2.41",
                "userAgent": "Canonical POS Test",
                "revokedAt": None,
                "lastSeenAtPresent": True,
            },
        )
        self.assertTrue(actual["restaurantAccessActive"])
        self.assertEqual(actual["roleCodes"], [self.role.code])
        self.assertEqual(
            actual["tariff"]["permissionCodes"], sorted(self.permission_codes)
        )
        self.assertEqual(actual["restaurant"]["restaurantRef"], "restaurant:primary")

    def test_pin_denials_preserve_current_messages(self):
        self._employee("duplicate-pin-characterization", "1111")
        cases = [
            ("wrong", "9999", ["Noto'g'ri PIN-kod."]),
            (
                "non-digit",
                "abcd",
                ["PIN-kod faqat raqamlardan iborat bo'lishi kerak."],
            ),
            ("too-long", "11111", ["Ensure this field has no more than 4 characters."]),
            ("inactive", "2222", ["This employee is inactive and cannot sign in."]),
            ("archived", "3333", ["This employee is archived and cannot sign in."]),
            (
                "duplicate",
                "1111",
                [
                    "Bu PIN-kod bir nechta POS foydalanuvchiga biriktirilgan. "
                    "Yagona PIN-kodlardan foydalaning."
                ],
            ),
        ]
        for case_id, pin, messages in cases:
            with self.subTest(case=case_id):
                response = self._post_pin(
                    self.restaurant, pin, ip=f"192.0.2.{50 + len(case_id)}"
                )
                actual = auth_scenario(
                    f"auth.remote.pin.{case_id}",
                    canonical_error(response.status_code, response.data),
                )
                self.assertEqual(actual, {"httpStatus": 400, "body": {"pin": messages}})

    def test_same_pin_is_scoped_by_selected_restaurant(self):
        other_restaurant = Restaurant.objects.create(
            name="Other characterization restaurant"
        )
        RestaurantEntitlement.objects.create(
            restaurant=other_restaurant,
            tariff=self.tariff,
            is_active=True,
            is_custom=False,
        )
        other_user = self._employee(
            "other-restaurant-user", "1111", restaurant=other_restaurant
        )
        refs = self._refs(
            users=[(self.user, "user:primary"), (other_user, "user:other")],
            restaurants=[
                (self.restaurant, "restaurant:primary"),
                (other_restaurant, "restaurant:other"),
            ],
        )

        primary = canonical_pin_session(
            200, self._post_pin(self.restaurant, "1111").data, **refs
        )
        other = canonical_pin_session(
            200, self._post_pin(other_restaurant, "1111").data, **refs
        )

        self.assertEqual(primary["user"]["userRef"], "user:primary")
        self.assertEqual(primary["restaurant"]["restaurantRef"], "restaurant:primary")
        self.assertEqual(other["user"]["userRef"], "user:other")
        self.assertEqual(other["restaurant"]["restaurantRef"], "restaurant:other")

    def test_pos_session_expiry_logout_and_surface_isolation(self):
        first = self._post_pin(self.restaurant, "1111", ip="192.0.2.61").data["token"]
        second = self._post_pin(self.restaurant, "1111", ip="192.0.2.62").data["token"]
        auth = lambda token: {"HTTP_AUTHORIZATION": f"Token {token}"}
        before = [
            self.client.get("/api/v1/pos/auth/me/", **auth(first)).status_code,
            self.client.get("/api/v1/pos/auth/me/", **auth(second)).status_code,
        ]
        logout = self.client.post("/api/v1/pos/auth/logout/", **auth(first)).status_code
        after_logout = [
            self.client.get("/api/v1/pos/auth/me/", **auth(first)).status_code,
            self.client.get("/api/v1/pos/auth/me/", **auth(second)).status_code,
        ]
        active_pos_sessions_after_logout = AuthSession.objects.filter(
            user=self.user,
            status="active",
            surface="pos",
        ).count()
        admin_token, _ = AuthSessionService().issue(
            user=self.user,
            request=APIRequestFactory().post("/", REMOTE_ADDR="192.0.2.63"),
            surface="admin",
        )
        cross_surface = [
            self.client.get("/api/v1/pos/auth/me/", **auth(admin_token)).status_code,
            self.client.get("/api/v1/admin/auth/me/", **auth(second)).status_code,
        ]
        AuthSession.objects.filter(
            token_key_hash=AuthSession.build_token_key_hash(second)
        ).update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.client.get("/api/v1/pos/auth/me/", **auth(second)).status_code

        actual = auth_scenario(
            "auth.remote.session.lifecycle",
            {
                "before": before,
                "logout": logout,
                "afterLogout": after_logout,
                "expired": expired,
                "crossSurface": cross_surface,
                "activePosSessionsAfterLogout": active_pos_sessions_after_logout,
            },
        )
        self.assertEqual(
            actual,
            {
                "before": [200, 200],
                "logout": 204,
                "afterLogout": [401, 200],
                "expired": 401,
                "crossSurface": [401, 401],
                "activePosSessionsAfterLogout": 1,
            },
        )

    def test_password_change_invalidates_existing_pos_session(self):
        token = self._post_pin(self.restaurant, "1111", ip="192.0.2.64").data["token"]
        self.user.set_password("changed-test-only-password")
        self.user.save(update_fields=["password"])

        response = self.client.get(
            "/api/v1/pos/auth/me/", HTTP_AUTHORIZATION=f"Token {token}"
        )

        self.assertEqual(
            auth_scenario(
                "auth.remote.session.password-change",
                {"httpStatus": response.status_code},
            ),
            {"httpStatus": 401},
        )
