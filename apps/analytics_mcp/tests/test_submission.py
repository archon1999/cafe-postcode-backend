import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from oauth2_provider.models import Application

from apps.analytics_mcp.management.commands.prepare_mcp_review import (
    USERNAME,
    TENANT_ID,
)
from apps.analytics_mcp.policy import authenticate_token
from apps.analytics_mcp.service import execute_report
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.users.models import User
from .test_analytics import SETTINGS, issue_fixture_token


@override_settings(**SETTINGS)
class SubmissionTests(TestCase):
    def test_domain_challenge_is_fail_closed_and_exact(self):
        path = "/.well-known/openai-apps-challenge"
        for token in ("", "bad\nvalue"):
            with patch.dict(os.environ, {"MCP_OPENAI_DOMAIN_CHALLENGE": token}):
                self.assertEqual(self.client.get(path).status_code, 404)
        with patch.dict(
            os.environ, {"MCP_OPENAI_DOMAIN_CHALLENGE": "issued-verification-token"}
        ):
            response = self.client.get(path)
            self.assertEqual(response.content, b"issued-verification-token")
            self.assertEqual(response["Cache-Control"], "no-store")

    @patch.dict(os.environ, {"MCP_REVIEW_PASSWORD": "test-only-long-review-password"})
    def test_demo_expected_results_and_no_reseed_or_foreign_access(self):
        foreign = Restaurant.objects.create(name="Unrelated customer")
        call_command("prepare_mcp_review", commit=True, stdout=StringIO())
        user = User.objects.get(username=USERNAME)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(
            set(user.permission_codes),
            {"dashboard.view", "reports.view", "expenses.view"},
        )
        app = Application.objects.create(
            name="Review test",
            client_type="confidential",
            authorization_grant_type="authorization-code",
        )
        raw, _ = issue_fixture_token(user, app, [Restaurant.objects.get(pk=TENANT_ID)])
        principal = authenticate_token(raw)
        args = {"period": "range", "start_date": "2026-09-07", "end_date": "2026-09-13"}
        summary = execute_report(principal, "get_sales_summary", args)["data"][
            "summary"
        ]
        self.assertEqual(summary["sales_total"], 1400000)
        self.assertEqual(summary["orders_count"], 28)
        series = execute_report(principal, "get_sales_timeseries", args)["data"]
        self.assertEqual(
            [p["sales_total"] for p in series["points"]],
            [50000 * n for n in range(1, 8)],
        )
        self.assertEqual(
            execute_report(principal, "get_expenses", args)["data"]["total_expenses"],
            35000,
        )
        for tool in (
            "get_top_products",
            "get_staff_performance",
            "get_table_performance",
            "get_payment_breakdown",
            "get_cash_shifts",
        ):
            self.assertTrue(execute_report(principal, tool, args)["data"])
        from apps.analytics_mcp.policy import AnalyticsError

        with self.assertRaises(AnalyticsError):
            execute_report(
                principal,
                "get_sales_summary",
                {**args, "branch_ids": [str(foreign.pk)]},
            )
        with self.assertRaises(CommandError):
            call_command("prepare_mcp_review", commit=True, stdout=StringIO())
        self.assertEqual(Order.objects.filter(restaurant_id=TENANT_ID).count(), 28)
        self.assertFalse(Order.objects.filter(restaurant=foreign).exists())
