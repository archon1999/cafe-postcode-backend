from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.reporting.selectors.reporting import (
    REPORT_PERIOD_DAY,
    REPORT_PERIOD_MONTH,
    REPORT_PERIOD_RANGE,
    REPORT_PERIOD_YEAR,
    ReportPeriod,
    build_summary_payload,
    get_top_items_report_queryset,
)
from common.utils.date import (
    as_edate,
    tashkent_day_bounds,
    tashkent_month_bounds,
    tashkent_year_bounds,
)


CORE_METRICS = ("sales_total", "orders_count", "average_check")


@dataclass(frozen=True)
class ReportMetricComparison:
    current: int
    previous: int
    difference: int
    change_percent: float | None

    def as_dict(self) -> dict:
        return {
            "current": self.current,
            "previous": self.previous,
            "difference": self.difference,
            "change_percent": self.change_percent,
        }


class CommonReportService:
    """Canonical sales report data shared by dashboard and Telegram views."""

    def build(
        self,
        *,
        restaurant,
        period: ReportPeriod,
        comparison_period: ReportPeriod | None = None,
        top_item_limit: int | None = 5,
        include_daily_breakdown: bool = False,
    ) -> dict:
        comparison_period = comparison_period or self.get_previous_period(period)
        summary = self.build_summary(restaurant, period)
        previous_summary = self.build_summary(restaurant, comparison_period)
        top_items = self.build_top_items(restaurant, period, limit=top_item_limit)

        payload = {
            "period": period,
            "comparison_period": comparison_period,
            "summary": summary,
            "previous_summary": previous_summary,
            "comparisons": self.build_comparisons(summary, previous_summary),
            "summary_delta": {
                key: self.get_change_percent(summary.get(key, 0), previous_summary.get(key, 0)) or 0.0
                for key in CORE_METRICS
            },
            "top_items": top_items,
        }
        if include_daily_breakdown:
            payload["daily_breakdown"] = self.build_daily_breakdown(
                restaurant=restaurant,
                period=period,
                comparison_period=comparison_period,
            )
        return payload

    @staticmethod
    def build_summary(restaurant, period: ReportPeriod) -> dict:
        return {key: int(value or 0) for key, value in build_summary_payload(restaurant, period).items()}

    @staticmethod
    def build_top_items(
        restaurant,
        period: ReportPeriod,
        *,
        limit: int | None = 5,
    ) -> list[dict]:
        queryset = get_top_items_report_queryset(restaurant, period).order_by(
            "-revenue", "-quantity", "catalog_item_name"
        )
        if limit is not None:
            queryset = queryset[:limit]
        return [
            {
                "catalog_item_id": row.get("catalog_item_id"),
                "item_name": row.get("catalog_item_name") or "Noma'lum",
                "category_id": row.get("category_id"),
                "category_name": row.get("category_name"),
                "quantity": CommonReportService._json_quantity(row.get("quantity")),
                "revenue": int(row.get("revenue") or 0),
            }
            for row in queryset
        ]

    @staticmethod
    def _json_quantity(value) -> int | float:
        quantity = Decimal(str(value or 0))
        return int(quantity) if quantity == quantity.to_integral_value() else float(quantity)

    def build_comparisons(self, summary: dict, previous_summary: dict) -> dict:
        comparisons = {}
        for key in CORE_METRICS:
            current = int(summary.get(key) or 0)
            previous = int(previous_summary.get(key) or 0)
            comparisons[key] = ReportMetricComparison(
                current=current,
                previous=previous,
                difference=current - previous,
                change_percent=self.get_change_percent(current, previous),
            ).as_dict()
        return comparisons

    def build_daily_breakdown(
        self,
        *,
        restaurant,
        period: ReportPeriod,
        comparison_period: ReportPeriod,
    ) -> list[dict]:
        day_count = self.get_period_day_span(period)
        comparison_day_count = self.get_period_day_span(comparison_period)
        if day_count != comparison_day_count:
            raise ValueError("Daily comparison periods must have the same number of days.")

        current_start = as_edate(period.start)
        previous_start = as_edate(comparison_period.start)
        rows = []
        for offset in range(day_count):
            current_date = as_edate(current_start + timedelta(days=offset))
            previous_date = as_edate(previous_start + timedelta(days=offset))
            current_summary = self.build_summary(restaurant, self.build_day_period(current_date))
            previous_summary = self.build_summary(restaurant, self.build_day_period(previous_date))
            current_sales = current_summary["sales_total"]
            previous_sales = previous_summary["sales_total"]
            rows.append(
                {
                    "date": current_date,
                    "comparison_date": previous_date,
                    "sales_total": current_sales,
                    "previous_sales_total": previous_sales,
                    "sales_difference": current_sales - previous_sales,
                    "orders_count": current_summary["orders_count"],
                    "average_check": current_summary["average_check"],
                }
            )
        return rows

    @staticmethod
    def get_change_percent(current: int, previous: int) -> float | None:
        if not previous:
            return None if current else 0.0
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def get_period_day_span(period: ReportPeriod) -> int:
        return (as_edate(period.end - timedelta(days=1)) - as_edate(period.start)).days + 1

    @staticmethod
    def build_day_period(value: date) -> ReportPeriod:
        value = as_edate(value)
        start, end = tashkent_day_bounds(value)
        iso_value = value.isoformat()
        return ReportPeriod(
            period_type=REPORT_PERIOD_DAY,
            start=start,
            end=end,
            value=iso_value,
            label=iso_value,
            file_label=f"day-{iso_value}",
        )

    @staticmethod
    def build_range_period(start_date: date, end_date: date) -> ReportPeriod:
        start_date = as_edate(start_date)
        end_date = as_edate(end_date)
        start, _ = tashkent_day_bounds(start_date)
        _, end = tashkent_day_bounds(end_date)
        value = f"{start_date.isoformat()} - {end_date.isoformat()}"
        return ReportPeriod(
            period_type=REPORT_PERIOD_RANGE,
            start=start,
            end=end,
            value=value,
            label=value,
            file_label=f"range-{start_date.isoformat()}-to-{end_date.isoformat()}",
        )

    @staticmethod
    def build_month_period(year: int, month: int) -> ReportPeriod:
        start, end = tashkent_month_bounds(year, month)
        value = f"{year:04d}-{month:02d}"
        return ReportPeriod(
            period_type=REPORT_PERIOD_MONTH,
            start=start,
            end=end,
            value=value,
            label=value,
            file_label=f"month-{value}",
        )

    def get_previous_period(self, period: ReportPeriod) -> ReportPeriod:
        if period.period_type == REPORT_PERIOD_RANGE:
            current_start = as_edate(period.start)
            span = self.get_period_day_span(period)
            previous_end = as_edate(current_start - timedelta(days=1))
            previous_start = as_edate(previous_end - timedelta(days=span - 1))
            return self.build_range_period(previous_start, previous_end)

        if period.period_type == REPORT_PERIOD_MONTH:
            year = period.start.year
            month = period.start.month - 1
            if month == 0:
                year -= 1
                month = 12
            return self.build_month_period(year, month)

        if period.period_type == REPORT_PERIOD_YEAR:
            year = period.start.year - 1
            start, end = tashkent_year_bounds(year)
            value = str(year)
            return ReportPeriod(
                period_type=REPORT_PERIOD_YEAR,
                start=start,
                end=end,
                value=value,
                label=value,
                file_label=f"year-{value}",
            )

        return self.build_day_period(as_edate(period.start) - timedelta(days=1))
