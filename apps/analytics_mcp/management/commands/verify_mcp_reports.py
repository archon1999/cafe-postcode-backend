"""Operator-only smoke check. All temporary OAuth/snapshot writes roll back."""

import json
import secrets
import time
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application
from apps.analytics_mcp.config import resource
from apps.analytics_mcp.models import AccessBinding, AnalyticsConnection
from apps.analytics_mcp.policy import (
    AnalyticsError,
    accessible_restaurants,
    authenticate_token,
)
from apps.analytics_mcp.service import execute_report, load_chart
from apps.analytics_mcp.contracts import PeriodInput, resolve_period
from apps.billing.models import CashExpense
from apps.reporting.selectors.reporting import build_summary_payload
from apps.users.models import User


class Command(BaseCommand):
    help = "Verify scoped reports for named existing restaurant users; temporary records are always rolled back."

    def add_arguments(self, parser):
        parser.add_argument("--username", action="append", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        app = Application.objects.create(
            name="MCP transactional verification",
            client_type="confidential",
            authorization_grant_type="authorization-code",
        )
        results = []
        try:
            for username in options["username"]:
                user = User.objects.get(username=username)
                branches = accessible_restaurants(user)
                consent = AnalyticsConnection.objects.create(
                    user=user,
                    application=app,
                    restaurant_ids=[str(r.pk) for r in branches],
                    resource=resource(),
                    expires_at=timezone.now() + timedelta(minutes=5),
                )
                raw = secrets.token_urlsafe(32)
                token = AccessToken.objects.create(
                    user=user,
                    application=app,
                    token=raw,
                    resource=[resource()],
                    scope="analytics:read",
                    expires=consent.expires_at,
                )
                AccessBinding.objects.create(access_token=token, connection=consent)
                principal = authenticate_token(raw)
                timings = {}
                reports = {}
                for period in ("today", "last_7_days"):
                    args = {"period": period}
                    for name in (
                        "get_sales_summary",
                        "get_sales_timeseries",
                        "get_top_products",
                        "get_expenses",
                        "get_staff_performance",
                        "get_table_performance",
                        "get_payment_breakdown",
                        "get_cash_shifts",
                    ):
                        started = time.monotonic()
                        report = execute_report(principal, name, args)
                        timings[period + ":" + name] = round(
                            (time.monotonic() - started) * 1000
                        )
                        if report["presentation"]["show_branches"] != (
                            len(branches) > 1
                        ):
                            raise CommandError("Incorrect scope presentation")
                        reports[name] = report
                    series = reports["get_sales_timeseries"]
                    chart = load_chart(principal, series["report_id"])
                    if chart != series:
                        raise CommandError("Chart payload mismatch")
                    # Use the exact cutoff returned by MCP to compare the canonical report.
                    from datetime import datetime
                    from apps.reporting.services import ReportPeriod

                    meta = reports["get_sales_summary"]["period"]
                    interval = ReportPeriod(
                        "range",
                        datetime.fromisoformat(meta["start_inclusive"]),
                        datetime.fromisoformat(meta["end_exclusive"]),
                        "",
                        "",
                        "",
                    )
                    canonical = build_summary_payload(branches, interval)
                    if reports["get_sales_summary"]["data"]["summary"] != canonical:
                        raise CommandError("Canonical summary mismatch")
                    # Full closed periods have stable boundaries for aggregate parity.
                    if period == "last_7_days":
                        fixed = {"period": "yesterday"}
                        summary = execute_report(principal, "get_sales_summary", fixed)[
                            "data"
                        ]["summary"]
                        points = execute_report(
                            principal, "get_sales_timeseries", fixed
                        )["data"]["totals"]
                        payment = execute_report(
                            principal, "get_payment_breakdown", fixed
                        )["data"]["totals"]
                        if (
                            summary["sales_total"] != points["sales_total"]
                            or summary["sales_total"] != payment["net_receipts"]
                        ):
                            raise CommandError("Summary/series/payment parity failure")
                        expense = execute_report(principal, "get_expenses", fixed)[
                            "data"
                        ]["total_expenses"]
                        interval, _ = resolve_period(PeriodInput(**fixed))
                        expected = (
                            CashExpense.objects.filter(
                                restaurant__in=branches,
                                status="posted",
                                occurred_at__gte=interval.start,
                                occurred_at__lt=interval.end,
                            ).aggregate(total=Sum("amount"))["total"]
                            or 0
                        )
                        if expense != expected:
                            raise CommandError("Expense parity failure")
                if len(branches) == 1:
                    try:
                        execute_report(principal, "compare_branches", {})
                    except AnalyticsError as error:
                        if error.code != "single_restaurant":
                            raise
                    else:
                        raise CommandError(
                            "Single restaurant comparison was not rejected"
                        )
                consent.revoked_at = timezone.now()
                consent.save(update_fields=["revoked_at"])
                try:
                    load_chart(principal, series["report_id"])
                except AnalyticsError:
                    pass
                else:
                    raise CommandError("Revoked snapshot remained readable")
                results.append(
                    {
                        "restaurant_names": [r.name for r in branches],
                        "single_restaurant": len(branches) == 1,
                        "checks": "passed",
                        "timings_ms": timings,
                    }
                )
        finally:
            transaction.set_rollback(True)
        self.stdout.write(
            json.dumps(
                {"results": results, "temporary_records": "rolled_back"},
                ensure_ascii=False,
            )
        )
