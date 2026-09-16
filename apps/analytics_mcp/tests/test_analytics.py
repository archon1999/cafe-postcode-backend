import base64
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application
from pydantic import ValidationError

from apps.analytics_mcp.config import resource
from apps.analytics_mcp.contracts import SeriesInput, TopProductsInput, resolve_period
from apps.analytics_mcp.models import AccessBinding, AnalyticsConnection, ReportSnapshot
from apps.analytics_mcp.policy import AnalyticsError, authenticate_token
from apps.analytics_mcp.service import execute_report, load_chart
from apps.billing.models import Payment, PaymentRefund
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import CashDesk, Restaurant
from apps.sales.models import Order, OrderItem
from apps.users.models import Permission, Role, User
from common.utils.date import TASHKENT_TIMEZONE
from core.settings.mcp import MCPSettings

SETTINGS = dict(
    ROOT_URLCONF="apps.analytics_mcp.urls",
    MIDDLEWARE=MCPSettings.MIDDLEWARE,
    MCP_PUBLIC_ORIGIN="http://127.0.0.1:8765",
    DISABLE_CSRF_CHECKS=False,
)


def fixtures():
    permission = Permission.objects.get(code="dashboard.view")
    role = Role.objects.create(code="mcp-test-owner", name="MCP test owner")
    role.permissions.set([permission])
    root = Restaurant.objects.create(name="MCP Root")
    branch = Restaurant.objects.create(name="MCP Branch", parent_restaurant=root)
    foreign = Restaurant.objects.create(name="Foreign business")
    for restaurant in (root, branch, foreign):
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=restaurant, is_active=True
        )
        entitlement.permissions.set([permission])
    user = User.objects.create_user(
        username="mcp-owner", password="test-only-password", restaurant=root, role=role
    )
    other = User.objects.create_user(
        username="mcp-other",
        password="test-only-password",
        restaurant=foreign,
        role=role,
    )
    app = Application(
        name="ChatGPT test",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://chatgpt.com/connector/oauth/test",
    )
    secret = app.client_secret
    app.save()
    return root, branch, foreign, user, other, app, secret


def issue_fixture_token(user, app, branches):
    connection = AnalyticsConnection.objects.create(
        user=user,
        application=app,
        restaurant_ids=[str(r.pk) for r in branches],
        resource=resource(),
        expires_at=timezone.now() + timedelta(days=1),
    )
    raw = uuid4().hex
    token = AccessToken.objects.create(
        user=user,
        application=app,
        token=raw,
        scope="analytics:read",
        resource=[resource()],
        expires=timezone.now() + timedelta(hours=1),
    )
    AccessBinding.objects.create(access_token=token, connection=connection)
    return raw, connection


@override_settings(**SETTINGS)
class ReportingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.root, self.branch, self.foreign, self.user, self.other, self.app, _ = (
            fixtures()
        )
        self.raw, self.connection = issue_fixture_token(
            self.user, self.app, [self.root, self.branch]
        )
        self.principal = authenticate_token(self.raw)
        self.args = {
            "period": "range",
            "start_date": "2026-01-02",
            "end_date": "2026-01-03",
        }
        desk = CashDesk.objects.create(restaurant=self.root, name="MCP desk")
        dt = datetime(2026, 1, 2, 12, tzinfo=TASHKENT_TIMEZONE)
        self.order = Order.objects.create(
            restaurant=self.root,
            order_number=1,
            status=Order.Status.CLOSED,
            total=10000,
            closed_at=dt,
        )
        self.payment = Payment.objects.create(
            order=self.order,
            cash_desk=desk,
            received_by=self.user,
            amount=10000,
            method=Payment.Method.CASH,
            status=Payment.Status.SUCCEEDED,
            paid_at=dt,
        )
        PaymentRefund.objects.create(
            payment=self.payment,
            amount=2000,
            status=PaymentRefund.Status.SUCCEEDED,
            refunded_at=dt + timedelta(days=1),
        )

    def test_summary_series_refund_parity(self):
        summary = execute_report(self.principal, "get_sales_summary", self.args)[
            "data"
        ]["summary"]
        series = execute_report(self.principal, "get_sales_timeseries", self.args)
        self.assertEqual(summary["sales_total"], 8000)
        self.assertEqual(
            series["data"]["totals"]["sales_total"], summary["sales_total"]
        )
        self.assertEqual(
            [p["sales_total"] for p in series["data"]["points"]], [10000, -2000]
        )
        self.assertEqual(series["data_freshness"]["status"], "unknown")
        self.assertEqual(load_chart(self.principal, series["report_id"]), series)

    def test_foreign_branch_and_forged_report_are_denied(self):
        with self.assertRaises(AnalyticsError):
            execute_report(
                self.principal,
                "get_sales_summary",
                {**self.args, "branch_ids": [str(self.foreign.pk)]},
            )
        result = execute_report(self.principal, "get_sales_timeseries", self.args)
        other_token, _ = issue_fixture_token(self.other, self.app, [self.foreign])
        with self.assertRaises(AnalyticsError):
            load_chart(authenticate_token(other_token), result["report_id"])
        with self.assertRaises(AnalyticsError):
            load_chart(self.principal, uuid4())

    def test_revocation_and_permission_changes_invalidate_saved_reports(self):
        result = execute_report(self.principal, "get_sales_timeseries", self.args)
        self.user.role.permissions.clear()
        with self.assertRaises(AnalyticsError):
            load_chart(self.principal, result["report_id"])
        self.user.role.permissions.add(Permission.objects.get(code="dashboard.view"))
        self.connection.revoked_at = timezone.now()
        self.connection.save()
        with self.assertRaises(AnalyticsError):
            authenticate_token(self.raw)

    def test_consent_does_not_expand_when_new_branch_is_added(self):
        added = Restaurant.objects.create(
            name="New branch", parent_restaurant=self.root
        )
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=added, is_active=True
        )
        entitlement.permissions.set([Permission.objects.get(code="dashboard.view")])
        result = execute_report(self.principal, "list_branches", {})
        self.assertNotIn(str(added.pk), [r["id"] for r in result["branches"]])

    def test_entitlement_and_empty_scope_fail_closed(self):
        self.branch.entitlement.is_active = False
        self.branch.entitlement.save()
        with self.assertRaises(AnalyticsError):
            execute_report(
                self.principal,
                "get_sales_summary",
                {**self.args, "branch_ids": [str(self.branch.pk)]},
            )
        self.connection.restaurant_ids = []
        self.connection.save()
        with self.assertRaises(AnalyticsError):
            execute_report(self.principal, "list_branches", {})

    def test_superuser_and_wrong_audience_rejected(self):
        AccessToken.objects.filter(token=self.raw).update(
            resource=["https://other.example/mcp"]
        )
        with self.assertRaises(AnalyticsError):
            authenticate_token(self.raw)
        AccessToken.objects.filter(token=self.raw).update(resource=[resource()])
        self.user.is_superuser = True
        self.user.save()
        with self.assertRaises(AnalyticsError):
            authenticate_token(self.raw)

    def test_expired_snapshot_and_access_token_rejected(self):
        result = execute_report(self.principal, "get_sales_timeseries", self.args)
        ReportSnapshot.objects.filter(pk=result["report_id"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(AnalyticsError):
            load_chart(self.principal, result["report_id"])
        AccessToken.objects.filter(token=self.raw).update(
            expires=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(AnalyticsError):
            execute_report(self.principal, "list_branches", {})

    def test_dates_units_and_input_bounds(self):
        with self.assertRaises(ValidationError):
            TopProductsInput(sort_by="quantity")
        with self.assertRaises(ValidationError):
            SeriesInput(branch_ids=[])
        with self.assertRaises(ValidationError):
            SeriesInput(user_id=str(self.other.pk))
        with self.assertRaises(AnalyticsError):
            resolve_period(
                SeriesInput(
                    period="range", start_date="2026-01-01", end_date="2026-12-31"
                )
            )
        now = datetime(2026, 1, 8, 0, 15, tzinfo=TASHKENT_TIMEZONE)
        period, meta = resolve_period(SeriesInput(period="last_7_days"), now)
        self.assertEqual(meta["start_date"], "2026-01-02")
        self.assertEqual(period.end, now)
        self.assertTrue(meta["is_partial"])

    def test_mixed_currency_summary_denied_but_comparison_preserves_currencies(self):
        self.branch.currency = "USD"
        self.branch.save()
        with self.assertRaises(AnalyticsError):
            execute_report(self.principal, "get_sales_summary", self.args)
        result = execute_report(self.principal, "compare_branches", self.args)
        self.assertIsNone(result["currency"])
        self.assertEqual(
            {r["currency"] for r in result["data"]["branches"]}, {"UZS", "USD"}
        )

    def test_products_preserve_units_and_refund_basis(self):
        category = CatalogCategory.objects.create(restaurant=self.root, name="Food")
        item = CatalogItem.objects.create(
            restaurant=self.root, category=category, name="Rice", price=10000
        )
        OrderItem.objects.create(
            order=self.order,
            catalog_item=item,
            quantity="1.250",
            unit_price=10000,
            sale_unit="kg",
        )
        result = execute_report(
            self.principal,
            "get_top_products",
            {**self.args, "sort_by": "quantity", "sale_unit": "kg"},
        )
        row = result["data"]["products"][0]
        self.assertEqual(row["quantity"], 1.25)
        self.assertEqual(row["sale_unit"], "kg")
        self.assertEqual(row["revenue"], 12500)
        self.assertIn("no refund allocation", result["metric_basis"]["revenue"])

    def test_comparison_uses_four_queries_and_matches_canonical_summary(self):
        from apps.analytics_mcp.reports.sales import compare_branches
        from apps.analytics_mcp.service import ReportContext
        from apps.reporting.selectors.reporting import build_summary_payload

        period, _ = resolve_period(SeriesInput(**self.args))
        context = ReportContext((self.root, self.branch), period=period)
        with self.assertNumQueries(4):
            rows = compare_branches(context, None)["branches"]
        self.assertEqual(
            {k: rows[0][k] for k in build_summary_payload((self.root,), period)},
            build_summary_payload((self.root,), period),
        )

    def test_midnight_end_exclusive_and_hourly_series(self):
        midnight = datetime(2026, 1, 3, 0, tzinfo=TASHKENT_TIMEZONE)
        Payment.objects.filter(pk=self.payment.pk).update(paid_at=midnight)
        result = execute_report(
            self.principal,
            "get_sales_timeseries",
            {
                "period": "range",
                "start_date": "2026-01-02",
                "end_date": "2026-01-02",
                "granularity": "hour",
            },
        )
        self.assertEqual(len(result["data"]["points"]), 24)
        self.assertEqual(result["data"]["totals"]["gross_sales_total"], 0)
        result = execute_report(
            self.principal,
            "get_sales_timeseries",
            {
                "period": "range",
                "start_date": "2026-01-03",
                "end_date": "2026-01-03",
                "granularity": "hour",
            },
        )
        self.assertEqual(result["data"]["points"][0]["gross_sales_total"], 10000)


@override_settings(**SETTINGS)
class OAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        (
            self.root,
            self.branch,
            self.foreign,
            self.user,
            self.other,
            self.app,
            self.secret,
        ) = fixtures()
        self.client.force_login(self.user)
        self.verifier = "v" * 64
        self.challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        self.params = {
            "client_id": self.app.client_id,
            "response_type": "code",
            "scope": "analytics:read",
            "redirect_uri": self.app.redirect_uris,
            "resource": resource(),
            "state": "test-state",
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
        }

    def authorize(self):
        response = self.client.get("/oauth/authorize/", self.params)
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post(
            "/oauth/authorize/", {**self.params, "allow": "true"}
        )
        self.assertEqual(response.status_code, 302, response.content)
        values = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(values["state"], ["test-state"])
        return values["code"][0]

    def exchange(self, code, verifier=None):
        return self.client.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.app.client_id,
                "client_secret": self.secret,
                "redirect_uri": self.app.redirect_uris,
                "code_verifier": verifier or self.verifier,
                "resource": resource(),
            },
        )

    def test_full_pkce_flow_rotation_and_revocation(self):
        code = self.authorize()
        response = self.exchange(code)
        self.assertEqual(response.status_code, 200, response.content)
        tokens = response.json()
        principal = authenticate_token(tokens["access_token"])
        self.assertEqual(principal.user_id, str(self.user.pk))
        self.assertNotEqual(
            AccessToken.objects.get(pk=principal.access_token_id).token,
            tokens["access_token"],
        )
        self.assertEqual(self.exchange(code).status_code, 400)
        refresh_response = self.client.post(
            "/oauth/token/",
            {
                "grant_type": "refresh_token",
                "client_id": self.app.client_id,
                "client_secret": self.secret,
                "refresh_token": tokens["refresh_token"],
                "resource": resource(),
            },
        )
        self.assertEqual(refresh_response.status_code, 200, refresh_response.content)
        refreshed = refresh_response.json()
        new_principal = authenticate_token(refreshed["access_token"])
        self.assertEqual(new_principal.connection_id, principal.connection_id)
        with self.assertRaises(AnalyticsError):
            authenticate_token(tokens["access_token"])
        self.client.post(
            "/oauth/connections/", {"connection_id": principal.connection_id}
        )
        with self.assertRaises(AnalyticsError):
            authenticate_token(refreshed["access_token"])
        response = self.client.post(
            "/oauth/token/",
            {
                "grant_type": "refresh_token",
                "client_id": self.app.client_id,
                "client_secret": self.secret,
                "refresh_token": refreshed["refresh_token"],
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_pkce_resource_and_redirect_fail(self):
        self.assertEqual(self.exchange(self.authorize(), "wrong" * 16).status_code, 400)
        self.assertEqual(
            self.client.get(
                "/oauth/authorize/",
                {**self.params, "resource": "https://foreign.test/mcp"},
            ).status_code,
            400,
        )
        response = self.client.get(
            "/oauth/authorize/",
            {**self.params, "redirect_uri": "https://foreign.test/steal"},
        )
        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(
            self.client.post(
                "/oauth/authorize/",
                {**self.params, "code_challenge_method": "plain", "allow": "true"},
            ).status_code,
            400,
        )

    def test_csrf_enforced_and_user_cannot_revoke_other_connection(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(
            strict.post(
                "/oauth/authorize/", {**self.params, "allow": "true"}
            ).status_code,
            403,
        )
        _, foreign = issue_fixture_token(self.other, self.app, [self.foreign])
        self.client.post("/oauth/connections/", {"connection_id": str(foreign.pk)})
        foreign.refresh_from_db()
        self.assertIsNone(foreign.revoked_at)

    def test_refresh_replay_revokes_family(self):
        tokens = self.exchange(self.authorize()).json()
        form = {
            "grant_type": "refresh_token",
            "client_id": self.app.client_id,
            "client_secret": self.secret,
            "refresh_token": tokens["refresh_token"],
            "resource": resource(),
        }
        refreshed = self.client.post("/oauth/token/", form).json()
        self.assertEqual(self.client.post("/oauth/token/", form).status_code, 400)
        with self.assertRaises(AnalyticsError):
            authenticate_token(refreshed["access_token"])


@override_settings(**SETTINGS)
class TransportTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.root, self.branch, self.foreign, self.user, _, self.app, _ = fixtures()
        self.raw, _ = issue_fixture_token(self.user, self.app, [self.root, self.branch])

    def test_actual_streamable_http_and_resource(self):
        from starlette.testclient import TestClient
        from apps.analytics_mcp.server import create_application, CHART_URI

        with TestClient(
            create_application(), base_url="http://127.0.0.1:8765"
        ) as client:
            self.assertEqual(client.post("/mcp", json={}).status_code, 401)
            self.assertEqual(
                client.get("/.well-known/oauth-protected-resource/mcp").json()[
                    "resource"
                ],
                resource(),
            )
            headers = {
                "Authorization": "Bearer " + self.raw,
                "Accept": "application/json, text/event-stream",
            }

            def rpc(method, params=None):
                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params or {},
                    },
                    headers=headers,
                )
                self.assertEqual(response.status_code, 200, response.text)
                return response.json()

            init = rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            )
            self.assertIn("serverInfo", init["result"])
            tools = rpc("tools/list")["result"]["tools"]
            self.assertEqual(len(tools), 11)
            listed = rpc("tools/call", {"name": "list_branches", "arguments": {}})[
                "result"
            ]
            self.assertFalse(listed.get("isError"), listed)
            self.assertEqual(len(listed["structuredContent"]["branches"]), 2)
            forbidden = rpc(
                "tools/call",
                {
                    "name": "get_sales_summary",
                    "arguments": {"branch_ids": [str(self.foreign.pk)]},
                },
            )["result"]
            self.assertTrue(forbidden["isError"])
            widget = rpc("resources/read", {"uri": CHART_URI})["result"]["contents"][0]
            self.assertIn("ui/initialize", widget["text"])
            self.assertEqual(widget["mimeType"], "text/html;profile=mcp-app")
