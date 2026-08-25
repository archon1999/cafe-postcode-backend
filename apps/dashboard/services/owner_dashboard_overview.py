from django.db.models import QuerySet

from apps.billing.helpers import get_payment_model
from apps.dashboard.services.owner_dashboard_periods import OwnerDashboardPeriodMixin
from apps.dashboard.services.owner_dashboard_queries import OwnerDashboardQueryMixin
from apps.dashboard.services.owner_dashboard_rows import OwnerDashboardRowsMixin
from apps.dashboard.services.owner_dashboard_series import OwnerDashboardSeriesMixin
from apps.reporting.services import CommonReportService, ReportPeriod, get_payment_breakdown_report_queryset
from apps.sales.helpers import get_order_model
from common.utils.date import tashkent_now

Order = get_order_model()
Payment = get_payment_model()


class OwnerDashboardBaseService(
    OwnerDashboardRowsMixin,
    OwnerDashboardQueryMixin,
    OwnerDashboardSeriesMixin,
    OwnerDashboardPeriodMixin,
):
    common_report_service_class = CommonReportService
    overview_top_item_limit = None
    overview_staff_limit = 5
    overview_open_checks_limit = 5
    overview_shift_limit = 4


class OwnerDashboardOverviewService(OwnerDashboardBaseService):
    def build(
        self,
        *,
        restaurant,
        period: ReportPeriod,
        restaurant_scope=None,
        is_all: bool = False,
    ) -> dict:
        report_scope = restaurant_scope or restaurant
        previous_period = self.get_previous_period(period)
        common_report = self.common_report_service_class().build(
            restaurant=report_scope,
            period=period,
            comparison_period=previous_period,
            top_item_limit=self.overview_top_item_limit,
        )
        current_summary = {
            **common_report["summary"],
            "open_checks": self.get_open_checks_queryset(report_scope, period).count(),
            "active_tables": self.get_active_tables_queryset(report_scope, period).count(),
        }
        previous_summary = {
            **common_report["previous_summary"],
            "open_checks": self.get_open_checks_queryset(report_scope, previous_period).count(),
            "active_tables": self.get_active_tables_queryset(report_scope, previous_period).count(),
        }
        current_expenses = self.build_expense_summary(report_scope, period)
        previous_expenses = self.build_expense_summary(report_scope, previous_period)
        current_summary.update(current_expenses)
        previous_summary.update(previous_expenses)
        series_blueprint = self.get_series_blueprint(period)
        revenue_series = self.build_revenue_series(
            report_scope, period, blueprint=series_blueprint
        )
        previous_revenue_series = self.build_revenue_series(
            report_scope,
            previous_period,
            blueprint=series_blueprint,
        )
        top_items = common_report["top_items"]
        waiters = self.get_role_breakdown_rows(report_scope, period, role="waiter")[
            : self.overview_staff_limit
        ]
        cashiers = self.get_role_breakdown_rows(report_scope, period, role="cashier")[
            : self.overview_staff_limit
        ]
        managers = self.get_role_breakdown_rows(report_scope, period, role="manager")[
            : self.overview_staff_limit
        ]
        payment_method_breakdown = self.build_choice_breakdown(
            list(get_payment_breakdown_report_queryset(report_scope, period)),
            Payment.Method.choices,
            total_sales=self.get_safe_number(current_summary.get("sales_total")),
        )
        channel_breakdown = self.build_choice_breakdown(
            list(self.get_channel_breakdown_queryset(report_scope, period)),
            Order.Channel.choices,
            total_sales=self.get_safe_number(current_summary.get("sales_total")),
        )
        open_checks_rows = self.build_open_checks_rows(
            report_scope,
            period,
            limit=self.overview_open_checks_limit,
        )
        shift_rows = self.build_shift_rows(
            report_scope, period, limit=self.overview_shift_limit
        )
        all_shift_rows = self.build_shift_rows(report_scope, period)

        return {
            "generated_at": tashkent_now(),
            "restaurant": {
                "id": restaurant.id,
                "name": "Barcha shahobchalar" if is_all else restaurant.name,
                "currency": restaurant.currency,
                "address": "" if is_all else restaurant.address,
            },
            "period": self.build_period_metadata(period, previous_period),
            "summary": {
                "sales_total": self.get_safe_number(current_summary.get("sales_total")),
                "orders_count": self.get_safe_number(
                    current_summary.get("orders_count")
                ),
                "average_check": self.get_safe_number(
                    current_summary.get("average_check")
                ),
                "open_checks": self.get_safe_number(current_summary.get("open_checks")),
                "active_tables": self.get_safe_number(
                    current_summary.get("active_tables")
                ),
                "expenses_total": self.get_safe_number(current_summary.get("expenses_total")),
                "expenses_count": self.get_safe_number(current_summary.get("expenses_count")),
            },
            "summary_delta": self.build_summary_delta(
                current_summary, previous_summary
            ),
            "spotlight": {
                "top_item": top_items[0] if top_items else None,
                "top_waiter": waiters[0] if waiters else None,
                "top_cashier": cashiers[0] if cashiers else None,
                "top_manager": managers[0] if managers else None,
                "top_channel": max(
                    channel_breakdown,
                    key=lambda row: (row["sales_total"], row["orders_count"]),
                )
                if channel_breakdown
                else None,
                "top_payment_method": max(
                    payment_method_breakdown,
                    key=lambda row: (row["sales_total"], row["orders_count"]),
                )
                if payment_method_breakdown
                else None,
                "peak_time_bucket": self.get_peak_time_bucket(revenue_series),
            },
            "revenue_series": revenue_series,
            "previous_revenue_series": previous_revenue_series,
            "top_items": top_items,
            "staff_breakdown": {
                "waiters": waiters,
                "cashiers": cashiers,
                "managers": managers,
            },
            "payment_method_breakdown": payment_method_breakdown,
            "channel_breakdown": channel_breakdown,
            "open_checks_snapshot": {
                "count": self.get_safe_number(current_summary.get("open_checks")),
                "active_tables": self.get_safe_number(
                    current_summary.get("active_tables")
                ),
                "rows": open_checks_rows,
            },
            "cash_shift_snapshot": {
                "open_count": sum(
                    1 for row in all_shift_rows if row["status"] == "open"
                ),
                "difference_count": sum(
                    1 for row in all_shift_rows if row["is_difference"]
                ),
                "cash_total": sum(row["cash_total"] for row in all_shift_rows),
                "card_total": sum(row["card_total"] for row in all_shift_rows),
                "qr_total": sum(row["qr_total"] for row in all_shift_rows),
                "refund_total": sum(row["refund_total"] for row in all_shift_rows),
                "expense_total": sum(row["expense_total"] for row in all_shift_rows),
                "receipt_count": sum(row["receipt_count"] for row in all_shift_rows),
                "rows": shift_rows,
            },
            "expense_snapshot": {
                "total": self.get_safe_number(current_summary.get("expenses_total")),
                "count": self.get_safe_number(current_summary.get("expenses_count")),
                "category_breakdown": [
                    {
                        "name": row.get("name") or "Noma'lum",
                        "total": self.get_safe_number(row.get("total")),
                        "count": self.get_safe_number(row.get("count")),
                    }
                    for row in self.get_expense_category_breakdown(report_scope, period)
                ],
                "rows": self.build_expense_rows(report_scope, period),
            },
        }


class OwnerDashboardDetailService(OwnerDashboardBaseService):
    def build_open_checks_queryset(
        self, *, restaurant, period: ReportPeriod
    ) -> QuerySet:
        return self.get_open_checks_queryset(restaurant, period)

    def build_top_items_queryset(self, *, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_top_items_queryset(restaurant, period)

    def build_staff_queryset(
        self, *, restaurant, period: ReportPeriod, role: str
    ) -> QuerySet:
        if role == "manager":
            return self.get_manager_queryset(restaurant, period)
        return (
            self.get_cashier_queryset(restaurant, period)
            if role == "cashier"
            else self.get_waiter_queryset(restaurant, period)
        )

    def build_shift_queryset(self, *, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_shift_queryset(restaurant, period)
