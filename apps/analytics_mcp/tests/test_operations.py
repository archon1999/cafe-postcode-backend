from datetime import timedelta

from django.template.loader import render_to_string
from django.test import TestCase, override_settings

from apps.billing.models import CashExpense, CashShift, ExpenseCategory, Payment
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.sales.models import Order, OrderItem
from apps.users.models import Permission
from apps.analytics_mcp.policy import AnalyticsError, authenticate_token
from apps.analytics_mcp.service import execute_report
from .test_analytics import SETTINGS, ReportingTests, issue_fixture_token


@override_settings(**SETTINGS)
class OperationsTests(TestCase):
    def setUp(self):
        ReportingTests.setUp(self)
        permissions = Permission.objects.filter(
            code__in=["reports.view", "expenses.view"]
        )
        self.user.role.permissions.add(*permissions)
        for branch in (self.root, self.branch):
            branch.entitlement.permissions.add(*permissions)
        self.desk = self.payment.cash_desk
        self.shift = CashShift.objects.create(
            cash_desk=self.desk,
            opened_by=self.user,
            opened_at=self.order.closed_at,
            status=CashShift.Status.OPEN,
        )

    def report(self, name, **extra):
        return execute_report(self.principal, name, {**self.args, **extra})

    def test_expenses_exclude_voided_foreign_and_outside_period(self):
        category = ExpenseCategory.objects.create(
            restaurant=self.root, name="Transport"
        )
        values = dict(
            restaurant=self.root,
            cash_shift=self.shift,
            cash_desk=self.desk,
            category=category,
            category_name_snapshot="Transport",
            created_by=self.user,
            occurred_at=self.order.closed_at,
            amount=500,
        )
        CashExpense.objects.create(**values)
        CashExpense.objects.create(
            **{**values, "status": CashExpense.Status.VOIDED, "amount": 900}
        )
        CashExpense.objects.create(
            **{**values, "restaurant": self.foreign, "amount": 800}
        )
        CashExpense.objects.create(
            **{
                **values,
                "occurred_at": self.order.closed_at - timedelta(days=2),
                "amount": 700,
            }
        )
        data = self.report("get_expenses")["data"]
        self.assertEqual(data["total_expenses"], 500)
        self.assertEqual(data["expense_count"], 1)
        self.assertEqual(data["categories"][0]["category"], "Transport")
        self.assertNotIn("recipient", str(data))

    def test_all_operational_tools_deny_foreign_scope(self):
        for name in (
            "get_expenses",
            "get_staff_performance",
            "get_table_performance",
            "get_payment_breakdown",
            "get_cash_shifts",
        ):
            with self.subTest(name=name), self.assertRaises(AnalyticsError):
                self.report(name, branch_ids=[str(self.foreign.pk)])

    def test_domain_permissions_and_entitlements_are_required(self):
        permission = Permission.objects.get(code="reports.view")
        self.user.role.permissions.remove(permission)
        with self.assertRaises(AnalyticsError):
            self.report("get_staff_performance")
        self.user.role.permissions.add(permission)
        self.branch.entitlement.permissions.remove(permission)
        with self.assertRaises(AnalyticsError):
            self.report("get_cash_shifts")

    def test_payment_method_refunds_and_mixed_amounts(self):
        Payment.objects.create(
            order=self.order,
            amount=3000,
            cash_amount=1000,
            card_amount=2000,
            method=Payment.Method.MIXED,
            status=Payment.Status.SUCCEEDED,
            paid_at=self.order.closed_at,
        )
        result = self.report("get_payment_breakdown")["data"]
        methods = {row["method"]: row for row in result["methods"]}
        self.assertEqual(methods["cash"]["net_receipts"], 8000)
        self.assertEqual(methods["mixed"]["gross_receipts"], 3000)
        self.assertEqual(result["totals"]["net_receipts"], 11000)

    def test_staff_counts_use_item_creator_without_mixing_units(self):
        category = CatalogCategory.objects.create(restaurant=self.root, name="Food")
        item = CatalogItem.objects.create(
            restaurant=self.root, category=category, name="Rice", price=1000
        )
        OrderItem.objects.create(
            order=self.order,
            catalog_item=item,
            created_by=self.user,
            quantity=2,
            unit_price=1000,
            line_total=2000,
        )
        OrderItem.objects.create(
            order=self.order,
            catalog_item=item,
            created_by=self.user,
            quantity=1,
            unit_price=1000,
            line_total=1000,
            status=OrderItem.Status.CANCELLED,
        )
        row = self.report("get_staff_performance")["data"]["staff"][0]
        self.assertEqual(row["staff_id"], str(self.user.pk))
        self.assertEqual(row["line_revenue"], 2000)
        self.assertEqual(row["orders_count"], 1)
        self.assertNotIn("quantity", row)

    def test_tables_exclude_takeaway_and_cancelled_orders(self):
        zone = ZoneOrCabin.objects.create(restaurant=self.root, name="Main")
        hall = Hall.objects.create(zone_or_cabin=zone, name="Main")
        table = DiningTable.objects.create(hall=hall, name="Table 1")
        session = TableSession.objects.create(
            restaurant=self.root, hall=hall, table=table
        )
        self.order.table_session = session
        self.order.save(update_fields=["table_session"])
        Order.objects.create(
            restaurant=self.root,
            order_number=2,
            status=Order.Status.CANCELLED,
            closed_at=self.order.closed_at,
            total=99999,
            table_session=session,
        )
        Order.objects.create(
            restaurant=self.root,
            order_number=3,
            status=Order.Status.CLOSED,
            closed_at=self.order.closed_at,
            total=555,
            channel=Order.Channel.TAKEAWAY,
        )
        result = self.report("get_table_performance")["data"]
        self.assertEqual(result["tables"][0]["order_total"], 10000)
        self.assertEqual(result["tables"][0]["orders_count"], 1)

    def test_shift_is_selected_by_opening_date_and_totals_remain_whole_shift(self):
        self.shift.cash_total = 12345
        self.shift.save(update_fields=["cash_total"])
        row = self.report("get_cash_shifts")["data"]["shifts"][0]
        self.assertEqual(row["cash_total"], 12345)
        self.assertIsNone(row["closed_at"])
        self.assertNotIn("cashier_name", row)

    def test_single_restaurant_has_no_branch_presentation_or_consent_label(self):
        raw, connection = issue_fixture_token(self.user, self.app, [self.root])
        principal = authenticate_token(raw)
        result = execute_report(principal, "list_branches", {})
        self.assertFalse(result["presentation"]["show_branches"])
        self.assertIn("restaurant", result["data"])
        self.assertNotIn("branches", result["data"])
        with self.assertRaises(AnalyticsError):
            execute_report(principal, "compare_branches", self.args)
        consent = render_to_string(
            "analytics_mcp/authorize.html",
            {"branches": [self.root], "application": self.app},
        )
        self.assertNotIn("Ulanadigan filiallar", consent)
        connections = render_to_string(
            "analytics_mcp/connections.html", {"connections": [connection]}
        )
        self.assertNotIn("1 filial", connections)

    def test_oauth_security_headers_and_asset_allowlist(self):
        response = self.client.get("/oauth/login/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("https://chatgpt.com", response["Content-Security-Policy"])
        asset = self.client.get("/assets/nunito-sans.woff2")
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset["Content-Type"], "font/woff2")
        self.assertTrue(b"".join(asset.streaming_content))
        self.assertEqual(self.client.get("/assets/config.env").status_code, 404)

    def test_existing_mfa_is_required_and_code_cannot_be_replayed(self):
        import time
        from cryptography.fernet import Fernet
        from django.utils import timezone
        from apps.analytics_mcp.views import AnalyticsLoginForm
        from apps.users.models import AdminMFAProfile
        from apps.users.services.admin_mfa import (
            encrypt_mfa_secret,
            generate_totp_secret,
            totp_code,
        )

        with override_settings(ADMIN_MFA_FERNET_KEYS=[Fernet.generate_key().decode()]):
            secret = generate_totp_secret()
            AdminMFAProfile.objects.create(
                user=self.user,
                encrypted_secret=encrypt_mfa_secret(secret),
                confirmed_at=timezone.now(),
            )
            credentials = {
                "username": self.user.username,
                "password": "test-only-password",
            }
            self.assertFalse(AnalyticsLoginForm(data=credentials).is_valid())
            valid = {**credentials, "otp": totp_code(secret, int(time.time()) // 30)}
            self.assertTrue(AnalyticsLoginForm(data=valid).is_valid())
            self.assertFalse(AnalyticsLoginForm(data=valid).is_valid())
