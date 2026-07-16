from datetime import timedelta

from apps.reporting.services import (
    REPORT_PERIOD_DAY,
    REPORT_PERIOD_MONTH,
    REPORT_PERIOD_RANGE,
    REPORT_PERIOD_YEAR,
    ReportPeriod,
)
from common.utils.date import (
    as_edate,
    tashkent_day_bounds,
    tashkent_month_bounds,
    tashkent_year_bounds,
)

MONTH_LABELS = (
    "Yan",
    "Fev",
    "Mar",
    "Apr",
    "May",
    "Iyn",
    "Iyul",
    "Avg",
    "Sen",
    "Okt",
    "Noy",
    "Dek",
)


class OwnerDashboardPeriodMixin:
    def get_period_start_date(self, period: ReportPeriod):
        return as_edate(period.start)

    def get_period_end_date(self, period: ReportPeriod):
        return as_edate(period.end - timedelta(days=1))

    def get_period_day_span(self, period: ReportPeriod) -> int:
        return (
            self.get_period_end_date(period) - self.get_period_start_date(period)
        ).days + 1

    def is_single_day_period(self, period: ReportPeriod) -> bool:
        return self.get_period_day_span(period) == 1

    def get_day_label(self, value) -> str:
        return f"{value.day:02d} {MONTH_LABELS[value.month - 1]} {value.year}"

    def get_range_label(self, period: ReportPeriod) -> str:
        start_date = self.get_period_start_date(period)
        end_date = self.get_period_end_date(period)

        if start_date == end_date:
            return self.get_day_label(start_date)

        if start_date.year == end_date.year and start_date.month == end_date.month:
            return f"{start_date.day:02d}-{end_date.day:02d} {MONTH_LABELS[start_date.month - 1]} {start_date.year}"

        if start_date.year == end_date.year:
            return (
                f"{start_date.day:02d} {MONTH_LABELS[start_date.month - 1]} - "
                f"{end_date.day:02d} {MONTH_LABELS[end_date.month - 1]} {start_date.year}"
            )

        return (
            f"{start_date.day:02d} {MONTH_LABELS[start_date.month - 1]} {start_date.year} - "
            f"{end_date.day:02d} {MONTH_LABELS[end_date.month - 1]} {end_date.year}"
        )

    def get_previous_period(self, period: ReportPeriod) -> ReportPeriod:
        if period.period_type == REPORT_PERIOD_RANGE:
            current_start = self.get_period_start_date(period)
            current_span = self.get_period_day_span(period)
            previous_end = current_start.yesterday()
            previous_start = as_edate(previous_end - timedelta(days=current_span - 1))
            start, _ = tashkent_day_bounds(previous_start)
            _, end = tashkent_day_bounds(previous_end)
            value = f"{previous_start.isoformat()}:{previous_end.isoformat()}"
            return ReportPeriod(
                period_type=REPORT_PERIOD_RANGE,
                start=start,
                end=end,
                value=value,
                label=value,
                file_label=f"range-{previous_start.isoformat()}-{previous_end.isoformat()}",
            )

        if period.period_type == REPORT_PERIOD_MONTH:
            year = period.start.year
            month = period.start.month - 1
            if month == 0:
                year -= 1
                month = 12
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

        previous_date = as_edate(period.start).yesterday()
        start, end = tashkent_day_bounds(previous_date)
        value = previous_date.isoformat()
        return ReportPeriod(
            period_type=REPORT_PERIOD_DAY,
            start=start,
            end=end,
            value=value,
            label=value,
            file_label=f"day-{value}",
        )

    def get_period_label(self, period: ReportPeriod) -> str:
        if period.period_type == REPORT_PERIOD_RANGE:
            return self.get_range_label(period)
        if period.period_type == REPORT_PERIOD_MONTH:
            return f"{MONTH_LABELS[period.start.month - 1]} {period.start.year}"
        if period.period_type == REPORT_PERIOD_YEAR:
            return str(period.start.year)
        return self.get_day_label(period.start)

    def get_chart_granularity(self, period: ReportPeriod) -> str:
        if period.period_type == REPORT_PERIOD_RANGE:
            return "hour" if self.is_single_day_period(period) else "day"
        if period.period_type == REPORT_PERIOD_YEAR:
            return "month"
        if period.period_type == REPORT_PERIOD_MONTH:
            return "day"
        return "hour"

    def build_period_metadata(
        self, period: ReportPeriod, comparison_period: ReportPeriod
    ) -> dict:
        return {
            "period_type": period.period_type,
            "value": period.value,
            "label": self.get_period_label(period),
            "start_date": self.get_period_start_date(period),
            "end_date": self.get_period_end_date(period),
            "comparison_value": comparison_period.value,
            "comparison_label": self.get_period_label(comparison_period),
            "comparison_start_date": self.get_period_start_date(comparison_period),
            "comparison_end_date": self.get_period_end_date(comparison_period),
            "chart_granularity": self.get_chart_granularity(period),
        }
