from __future__ import annotations

from datetime import date, timedelta

from django.template.loader import render_to_string

from apps.reporting.services import CommonReportService
from apps.telegram_reports.formatters import (
    build_weekly_grid,
    format_compact_money,
    format_percent,
    format_quantity,
)
from apps.telegram_reports.models import TelegramReportDelivery
from common.utils.date import as_edate, tashkent_today


MONTH_NAMES = (
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
)


class TelegramReportService:
    common_report_service_class = CommonReportService

    def build_scheduled_period(self, report_type: str, *, today: date | None = None):
        today = as_edate(today or tashkent_today())
        common = self.common_report_service_class()
        if report_type == TelegramReportDelivery.ReportType.DAILY:
            return common.build_day_period(today - timedelta(days=1))
        if report_type == TelegramReportDelivery.ReportType.WEEKLY:
            previous_sunday = as_edate(today - timedelta(days=today.weekday() + 1))
            previous_monday = as_edate(previous_sunday - timedelta(days=6))
            return common.build_range_period(previous_monday, previous_sunday)
        if report_type == TelegramReportDelivery.ReportType.MONTHLY:
            previous_month_end = as_edate(today.replace(day=1) - timedelta(days=1))
            return common.build_month_period(previous_month_end.year, previous_month_end.month)
        raise ValueError(f"Unsupported Telegram report type: {report_type}")

    def build_today_period(self, *, today: date | None = None):
        return self.common_report_service_class().build_day_period(today or tashkent_today())

    def build_current_period(self, report_type: str, *, today: date | None = None):
        today = as_edate(today or tashkent_today())
        common = self.common_report_service_class()
        if report_type == TelegramReportDelivery.ReportType.DAILY:
            return common.build_day_period(today)
        if report_type == TelegramReportDelivery.ReportType.WEEKLY:
            week_start = as_edate(today - timedelta(days=today.weekday()))
            return common.build_range_period(week_start, today)
        if report_type == TelegramReportDelivery.ReportType.MONTHLY:
            return common.build_month_period(today.year, today.month)
        raise ValueError(f"Unsupported Telegram report type: {report_type}")

    def render(self, *, restaurant, report_type: str, period=None) -> str:
        period = period or self.build_scheduled_period(report_type)
        include_daily = report_type == TelegramReportDelivery.ReportType.WEEKLY
        report = self.common_report_service_class().build(
            restaurant=restaurant,
            period=period,
            top_item_limit=None,
            include_daily_breakdown=include_daily,
        )
        context = {
            "branch_name": restaurant.name,
            "period_label": self.get_period_label(report_type, period),
            "metrics": self.build_metric_rows(report),
            "top_items": [
                {
                    **row,
                    "position": index,
                    "formatted_revenue": format_compact_money(row["revenue"]),
                    "formatted_quantity": format_quantity(row["quantity"]),
                    "quantity_unit": self.get_quantity_unit(row),
                }
                for index, row in enumerate(report["top_items"], start=1)
            ],
        }
        if include_daily:
            context["weekly_grid"] = build_weekly_grid(report["daily_breakdown"])
        return render_to_string(f"telegram_reports/{report_type}_report.html", context).strip()

    @staticmethod
    def get_quantity_unit(row: dict) -> str:
        if row.get("sale_unit") == "kg":
            return "kg"
        if row.get("item_type") == "service":
            return "ta xizmat"
        return "ta"

    @staticmethod
    def build_metric_rows(report: dict) -> list[dict]:
        specs = (
            ("sales_total", "💰", "Tushum", True),
            ("orders_count", "🧾", "Buyurtmalar", False),
            ("average_check", "🎯", "O‘rtacha chek", True),
        )
        rows = []
        for key, icon, title, is_money in specs:
            comparison = report["comparisons"][key]
            current = comparison["current"]
            previous = comparison["previous"]
            difference = comparison["difference"]
            if is_money:
                formatted_value = format_compact_money(current)
                formatted_previous = format_compact_money(previous)
            else:
                formatted_value = f"{current} ta"
                formatted_previous = f"{previous} ta"

            if previous == 0 and current > 0:
                trend_icon = "🆕"
                trend_text = "oldingi davrda ko‘rsatkich bo‘lmagan"
            elif difference > 0:
                trend_icon = "📈"
                trend_text = f"{format_percent(comparison['change_percent'])} • oldingi davr: {formatted_previous}"
            elif difference < 0:
                trend_icon = "📉"
                trend_text = f"{format_percent(comparison['change_percent'])} • oldingi davr: {formatted_previous}"
            else:
                trend_icon = "➖"
                trend_text = f"o‘zgarish yo‘q • oldingi davr: {formatted_previous}"
            rows.append(
                {
                    "icon": icon,
                    "title": title,
                    "formatted_value": formatted_value,
                    "trend_icon": trend_icon,
                    "trend_text": trend_text,
                }
            )
        return rows

    @staticmethod
    def get_period_label(report_type: str, period) -> str:
        start = as_edate(period.start)
        end = as_edate(period.end - timedelta(days=1))
        if report_type == TelegramReportDelivery.ReportType.DAILY:
            return f"{start.day} {MONTH_NAMES[start.month - 1]} {start.year}"
        if report_type == TelegramReportDelivery.ReportType.MONTHLY:
            return f"{MONTH_NAMES[start.month - 1]} {start.year}"
        return f"{start.day} {MONTH_NAMES[start.month - 1]} – {end.day} {MONTH_NAMES[end.month - 1]} {end.year}"
