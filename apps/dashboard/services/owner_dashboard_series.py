from calendar import monthrange
from datetime import timedelta

from django.db.models import Count, IntegerField, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncHour, TruncMonth

from apps.dashboard.services.owner_dashboard_periods import MONTH_LABELS
from apps.reporting.services import (
    REPORT_PERIOD_MONTH,
    REPORT_PERIOD_RANGE,
    REPORT_PERIOD_YEAR,
    ReportPeriod,
)
from common.utils.date import TASHKENT_TIMEZONE, as_edate


class OwnerDashboardSeriesMixin:
    def get_revenue_bucket_rows(self, queryset: QuerySet, period: ReportPeriod, *, field_name: str) -> dict[int, int]:
        if period.period_type == REPORT_PERIOD_YEAR:
            rows = (
                queryset.annotate(bucket=TruncMonth(field_name, tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()))
            )
            return {
                row['bucket'].month: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        if period.period_type == REPORT_PERIOD_RANGE and not self.is_single_day_period(period):
            start_date = self.get_period_start_date(period)
            rows = (
                queryset.annotate(bucket=TruncDate(field_name, tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()))
            )
            return {
                (as_edate(row['bucket']) - start_date).days: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        if period.period_type == REPORT_PERIOD_MONTH:
            rows = (
                queryset.annotate(bucket=TruncDate(field_name, tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()))
            )
            return {
                row['bucket'].day: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        rows = (
            queryset.annotate(bucket=TruncHour(field_name, tzinfo=TASHKENT_TIMEZONE))
            .values('bucket')
            .annotate(total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()))
        )
        return {
            row['bucket'].hour: self.get_safe_number(row.get('total'))
            for row in rows
            if row.get('bucket') is not None
        }

    def get_orders_bucket_rows(self, queryset: QuerySet, period: ReportPeriod) -> dict[int, int]:
        if period.period_type == REPORT_PERIOD_YEAR:
            rows = (
                queryset.annotate(bucket=TruncMonth('closed_at', tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Count('id'))
            )
            return {
                row['bucket'].month: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        if period.period_type == REPORT_PERIOD_RANGE and not self.is_single_day_period(period):
            start_date = self.get_period_start_date(period)
            rows = (
                queryset.annotate(bucket=TruncDate('closed_at', tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Count('id'))
            )
            return {
                (as_edate(row['bucket']) - start_date).days: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        if period.period_type == REPORT_PERIOD_MONTH:
            rows = (
                queryset.annotate(bucket=TruncDate('closed_at', tzinfo=TASHKENT_TIMEZONE))
                .values('bucket')
                .annotate(total=Count('id'))
            )
            return {
                row['bucket'].day: self.get_safe_number(row.get('total'))
                for row in rows
                if row.get('bucket') is not None
            }

        rows = (
            queryset.annotate(bucket=TruncHour('closed_at', tzinfo=TASHKENT_TIMEZONE))
            .values('bucket')
            .annotate(total=Count('id'))
        )
        return {
            row['bucket'].hour: self.get_safe_number(row.get('total'))
            for row in rows
            if row.get('bucket') is not None
        }

    def get_series_blueprint(self, period: ReportPeriod) -> list[dict]:
        if period.period_type == REPORT_PERIOD_YEAR:
            return [
                {'bucket_index': month, 'label': MONTH_LABELS[month - 1]}
                for month in range(1, 13)
            ]

        if period.period_type == REPORT_PERIOD_RANGE:
            if self.is_single_day_period(period):
                return [{'bucket_index': hour, 'label': f'{hour:02d}:00'} for hour in range(24)]

            start_date = self.get_period_start_date(period)
            return [
                {
                    'bucket_index': day_offset,
                    'label': self.get_day_label(as_edate(start_date + timedelta(days=day_offset))),
                }
                for day_offset in range(self.get_period_day_span(period))
            ]

        if period.period_type == REPORT_PERIOD_MONTH:
            day_count = monthrange(period.start.year, period.start.month)[1]
            return [{'bucket_index': day, 'label': f'{day:02d}'} for day in range(1, day_count + 1)]

        return [{'bucket_index': hour, 'label': f'{hour:02d}:00'} for hour in range(24)]

    def build_revenue_series(self, restaurant, period: ReportPeriod, *, blueprint: list[dict] | None = None) -> list[dict]:
        sales_map = self.get_revenue_bucket_rows(
            self.get_payment_queryset(restaurant, period),
            period,
            field_name='paid_at',
        )
        orders_map = self.get_orders_bucket_rows(self.get_closed_orders_queryset(restaurant, period), period)
        series = []

        for point in blueprint or self.get_series_blueprint(period):
            bucket_index = point['bucket_index']
            sales_total = sales_map.get(bucket_index, 0)
            orders_count = orders_map.get(bucket_index, 0)
            series.append(
                {
                    'bucket_index': bucket_index,
                    'label': point['label'],
                    'sales_total': sales_total,
                    'orders_count': orders_count,
                    'average_check': round(sales_total / orders_count) if orders_count else 0,
                }
            )

        return series

    def get_peak_time_bucket(self, revenue_series: list[dict]) -> dict:
        if not revenue_series:
            return {'bucket_index': 0, 'label': '-', 'sales_total': 0, 'orders_count': 0}

        peak_row = max(
            revenue_series,
            key=lambda row: (self.get_safe_number(row.get('sales_total')), self.get_safe_number(row.get('orders_count'))),
        )
        return {
            'bucket_index': peak_row['bucket_index'],
            'label': peak_row['label'],
            'sales_total': self.get_safe_number(peak_row.get('sales_total')),
            'orders_count': self.get_safe_number(peak_row.get('orders_count')),
        }
