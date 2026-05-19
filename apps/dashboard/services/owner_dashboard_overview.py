from calendar import monthrange
from datetime import timedelta

from django.db.models import Count, F, IntegerField, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncHour, TruncMonth

from apps.billing.helpers import get_payment_model
from apps.reporting.services import (
    REPORT_PERIOD_DAY,
    REPORT_PERIOD_MONTH,
    REPORT_PERIOD_RANGE,
    REPORT_PERIOD_YEAR,
    ReportPeriod,
    build_summary_payload,
    get_open_checks_report_queryset,
    get_payment_breakdown_report_queryset,
    get_shift_report_queryset,
    get_top_items_report_queryset,
    get_top_staff_report_queryset,
)
from apps.sales.helpers import get_order_model
from common.utils.date import (
    TASHKENT_TIMEZONE,
    as_edate,
    tashkent_day_bounds,
    tashkent_month_bounds,
    tashkent_now,
    tashkent_year_bounds,
)

Order = get_order_model()
Payment = get_payment_model()

MONTH_LABELS = (
    'Yan',
    'Fev',
    'Mar',
    'Apr',
    'May',
    'Iyn',
    'Iyul',
    'Avg',
    'Sen',
    'Okt',
    'Noy',
    'Dek',
)


class OwnerDashboardBaseService:
    overview_top_item_limit = 6
    overview_staff_limit = 5
    overview_open_checks_limit = 5
    overview_shift_limit = 4

    def get_period_start_date(self, period: ReportPeriod):
        return as_edate(period.start)

    def get_period_end_date(self, period: ReportPeriod):
        return as_edate(period.end - timedelta(days=1))

    def get_period_day_span(self, period: ReportPeriod) -> int:
        return (self.get_period_end_date(period) - self.get_period_start_date(period)).days + 1

    def is_single_day_period(self, period: ReportPeriod) -> bool:
        return self.get_period_day_span(period) == 1

    def get_day_label(self, value) -> str:
        return f'{value.day:02d} {MONTH_LABELS[value.month - 1]} {value.year}'

    def get_range_label(self, period: ReportPeriod) -> str:
        start_date = self.get_period_start_date(period)
        end_date = self.get_period_end_date(period)

        if start_date == end_date:
            return self.get_day_label(start_date)

        if start_date.year == end_date.year and start_date.month == end_date.month:
            return f'{start_date.day:02d}-{end_date.day:02d} {MONTH_LABELS[start_date.month - 1]} {start_date.year}'

        if start_date.year == end_date.year:
            return (
                f'{start_date.day:02d} {MONTH_LABELS[start_date.month - 1]} - '
                f'{end_date.day:02d} {MONTH_LABELS[end_date.month - 1]} {start_date.year}'
            )

        return (
            f'{start_date.day:02d} {MONTH_LABELS[start_date.month - 1]} {start_date.year} - '
            f'{end_date.day:02d} {MONTH_LABELS[end_date.month - 1]} {end_date.year}'
        )

    def get_previous_period(self, period: ReportPeriod) -> ReportPeriod:
        if period.period_type == REPORT_PERIOD_RANGE:
            current_start = self.get_period_start_date(period)
            current_span = self.get_period_day_span(period)
            previous_end = current_start.yesterday()
            previous_start = as_edate(previous_end - timedelta(days=current_span - 1))
            start, _ = tashkent_day_bounds(previous_start)
            _, end = tashkent_day_bounds(previous_end)
            value = f'{previous_start.isoformat()}:{previous_end.isoformat()}'
            return ReportPeriod(
                period_type=REPORT_PERIOD_RANGE,
                start=start,
                end=end,
                value=value,
                label=value,
                file_label=f'range-{previous_start.isoformat()}-{previous_end.isoformat()}',
            )

        if period.period_type == REPORT_PERIOD_MONTH:
            year = period.start.year
            month = period.start.month - 1
            if month == 0:
                year -= 1
                month = 12
            start, end = tashkent_month_bounds(year, month)
            value = f'{year:04d}-{month:02d}'
            return ReportPeriod(
                period_type=REPORT_PERIOD_MONTH,
                start=start,
                end=end,
                value=value,
                label=value,
                file_label=f'month-{value}',
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
                file_label=f'year-{value}',
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
            file_label=f'day-{value}',
        )

    def get_payment_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return Payment.objects.filter(
            order__restaurant=restaurant,
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=period.start,
            paid_at__lt=period.end,
        )

    def get_closed_orders_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return Order.objects.filter(
            restaurant=restaurant,
            closed_at__gte=period.start,
            closed_at__lt=period.end,
        ).exclude(status=Order.Status.CANCELLED)

    def get_top_items_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_top_items_report_queryset(restaurant, period).order_by(
            '-revenue',
            '-quantity',
            'catalog_item_name',
        )

    def get_waiter_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_top_staff_report_queryset(restaurant, period).order_by(
            '-total_sales',
            '-order_count',
            'staff_name',
        )

    def get_cashier_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return (
            self.get_payment_queryset(restaurant, period)
            .values(
                user_id=F('received_by__id'),
                user_name=F('received_by__full_name'),
            )
            .annotate(
                orders_count=Count('order_id', distinct=True),
                sales_total=Coalesce(Sum('amount'), Value(0), output_field=IntegerField()),
            )
            .order_by('-sales_total', '-orders_count', 'user_name')
        )

    def get_channel_breakdown_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return (
            self.get_closed_orders_queryset(restaurant, period)
            .values(code=F('channel'))
            .annotate(
                orders_count=Count('id'),
                sales_total=Coalesce(Sum('total'), Value(0), output_field=IntegerField()),
            )
            .order_by('-sales_total', 'code')
        )

    def get_open_checks_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_open_checks_report_queryset(restaurant, period).order_by('-created_at', '-order_number')

    def get_shift_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_shift_report_queryset(restaurant, period).order_by('-opened_at')

    def get_role_breakdown_rows(self, restaurant, period: ReportPeriod, *, role: str) -> list[dict]:
        if role == 'cashier':
            queryset = self.get_cashier_queryset(restaurant, period)
            name_key = 'user_name'
            orders_key = 'orders_count'
            sales_key = 'sales_total'
            user_key = 'user_id'
        else:
            queryset = self.get_waiter_queryset(restaurant, period)
            name_key = 'staff_name'
            orders_key = 'order_count'
            sales_key = 'total_sales'
            user_key = 'staff_id'

        rows = []
        for row in queryset:
            orders_count = self.get_safe_number(row.get(orders_key))
            sales_total = self.get_safe_number(row.get(sales_key))
            rows.append(
                {
                    'user_id': row.get(user_key),
                    'user_name': row.get(name_key),
                    'orders_count': orders_count,
                    'sales_total': sales_total,
                    'average_check': round(sales_total / orders_count) if orders_count else 0,
                }
            )
        return rows

    @staticmethod
    def get_safe_number(value) -> int:
        return int(value or 0)

    def build_choice_breakdown(self, rows: list[dict], choices, *, total_sales: int) -> list[dict]:
        rows_by_code = {
            (row.get('code') or row.get('method')): row
            for row in rows
            if row.get('code') or row.get('method')
        }
        breakdown = []

        for code, label in choices:
            row = rows_by_code.get(code, {})
            sales_total = self.get_safe_number(row.get('sales_total') or row.get('total'))
            orders_count = self.get_safe_number(row.get('orders_count') or row.get('count'))
            share = round((sales_total / total_sales) * 100) if total_sales > 0 else 0
            breakdown.append(
                {
                    'code': code,
                    'label': label,
                    'orders_count': orders_count,
                    'sales_total': sales_total,
                    'share': share,
                }
            )

        return breakdown

    def get_period_label(self, period: ReportPeriod) -> str:
        if period.period_type == REPORT_PERIOD_RANGE:
            return self.get_range_label(period)
        if period.period_type == REPORT_PERIOD_MONTH:
            return f'{MONTH_LABELS[period.start.month - 1]} {period.start.year}'
        if period.period_type == REPORT_PERIOD_YEAR:
            return str(period.start.year)
        return self.get_day_label(period.start)

    def get_chart_granularity(self, period: ReportPeriod) -> str:
        if period.period_type == REPORT_PERIOD_RANGE:
            return 'hour' if self.is_single_day_period(period) else 'day'
        if period.period_type == REPORT_PERIOD_YEAR:
            return 'month'
        if period.period_type == REPORT_PERIOD_MONTH:
            return 'day'
        return 'hour'

    def build_period_metadata(self, period: ReportPeriod, comparison_period: ReportPeriod) -> dict:
        return {
            'period_type': period.period_type,
            'value': period.value,
            'label': self.get_period_label(period),
            'start_date': self.get_period_start_date(period),
            'end_date': self.get_period_end_date(period),
            'comparison_value': comparison_period.value,
            'comparison_label': self.get_period_label(comparison_period),
            'comparison_start_date': self.get_period_start_date(comparison_period),
            'comparison_end_date': self.get_period_end_date(comparison_period),
            'chart_granularity': self.get_chart_granularity(period),
        }

    def build_summary_delta(self, current_summary: dict, previous_summary: dict) -> dict:
        return {
            'sales_total': self.get_change_pct(
                current_summary.get('sales_total', 0),
                previous_summary.get('sales_total', 0),
            ),
            'orders_count': self.get_change_pct(
                current_summary.get('orders_count', 0),
                previous_summary.get('orders_count', 0),
            ),
            'average_check': self.get_change_pct(
                current_summary.get('average_check', 0),
                previous_summary.get('average_check', 0),
            ),
            'open_checks': self.get_change_pct(
                current_summary.get('open_checks', 0),
                previous_summary.get('open_checks', 0),
            ),
            'active_tables': self.get_change_pct(
                current_summary.get('active_tables', 0),
                previous_summary.get('active_tables', 0),
            ),
        }

    def get_change_pct(self, current_value: int, previous_value: int) -> float:
        if not previous_value:
            return 100.0 if current_value > 0 else 0.0
        return round(((current_value - previous_value) / previous_value) * 100, 2)

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
                {
                    'bucket_index': month,
                    'label': MONTH_LABELS[month - 1],
                }
                for month in range(1, 13)
            ]

        if period.period_type == REPORT_PERIOD_RANGE:
            if self.is_single_day_period(period):
                return [
                    {
                        'bucket_index': hour,
                        'label': f'{hour:02d}:00',
                    }
                    for hour in range(24)
                ]

            start_date = self.get_period_start_date(period)
            total_days = self.get_period_day_span(period)
            return [
                {
                    'bucket_index': day_offset,
                    'label': self.get_day_label(as_edate(start_date + timedelta(days=day_offset))),
                }
                for day_offset in range(total_days)
            ]

        if period.period_type == REPORT_PERIOD_MONTH:
            day_count = monthrange(period.start.year, period.start.month)[1]
            return [
                {
                    'bucket_index': day,
                    'label': f'{day:02d}',
                }
                for day in range(1, day_count + 1)
            ]

        return [
            {
                'bucket_index': hour,
                'label': f'{hour:02d}:00',
            }
            for hour in range(24)
        ]

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
            return {
                'bucket_index': 0,
                'label': '-',
                'sales_total': 0,
                'orders_count': 0,
            }

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

    def build_top_items(self, restaurant, period: ReportPeriod, *, limit: int | None = None) -> list[dict]:
        queryset = self.get_top_items_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]

        rows = []
        for row in queryset:
            quantity = self.get_safe_number(row.get('quantity'))
            revenue = self.get_safe_number(row.get('revenue'))
            rows.append(
                {
                    'catalog_item_id': row.get('catalog_item_id'),
                    'item_name': row.get('catalog_item_name'),
                    'category_id': row.get('category_id'),
                    'category_name': row.get('category_name'),
                    'quantity': quantity,
                    'revenue': revenue,
                }
            )
        return rows

    def build_open_checks_rows(self, restaurant, period: ReportPeriod, *, limit: int | None = None) -> list[dict]:
        queryset = self.get_open_checks_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]

        return [
            {
                'id': row['id'],
                'order_number': row['order_number'],
                'status': row['status'],
                'total': self.get_safe_number(row.get('total')),
                'created_at': row['created_at'],
                'hall_id': row.get('hall_id'),
                'hall_name': row.get('hall_name'),
                'table_name': row.get('table_name'),
            }
            for row in queryset
        ]

    def build_shift_rows(self, restaurant, period: ReportPeriod, *, limit: int | None = None) -> list[dict]:
        queryset = self.get_shift_queryset(restaurant, period)
        if limit:
            queryset = queryset[:limit]

        rows = []
        for row in queryset:
            cash_total = self.get_safe_number(row.get('cash_total'))
            card_total = self.get_safe_number(row.get('card_total'))
            qr_total = self.get_safe_number(row.get('qr_total'))
            row_payload = {
                'id': row['id'],
                'status': row['status'],
                'opened_at': row['opened_at'],
                'closed_at': row.get('closed_at'),
                'opening_cash_amount': self.get_safe_number(row.get('opening_cash_amount')),
                'actual_closing_cash_amount': self.get_safe_number(row.get('actual_closing_cash_amount')),
                'expected_closing_cash_amount': self.get_safe_number(row.get('expected_closing_cash_amount')),
                'cash_difference_amount': self.get_safe_number(row.get('cash_difference_amount')),
                'cash_total': cash_total,
                'card_total': card_total,
                'qr_total': qr_total,
                'refund_total': self.get_safe_number(row.get('refund_total')),
                'receipt_count': self.get_safe_number(row.get('receipt_count')),
                'reprint_count': self.get_safe_number(row.get('reprint_count')),
                'cash_desk_id': row.get('cash_desk_id'),
                'cash_desk_name': row.get('cash_desk_name'),
                'cashier_id': row.get('cashier_id') or row.get('opened_by_id'),
                'cashier_name': row.get('cashier_name'),
                'gross_total': cash_total + card_total + qr_total,
                'is_difference': bool(self.get_safe_number(row.get('cash_difference_amount'))),
            }
            rows.append(row_payload)
        return rows


class OwnerDashboardOverviewService(OwnerDashboardBaseService):
    def build(self, *, restaurant, period: ReportPeriod) -> dict:
        previous_period = self.get_previous_period(period)
        current_summary = build_summary_payload(restaurant, period)
        previous_summary = build_summary_payload(restaurant, previous_period)
        series_blueprint = self.get_series_blueprint(period)
        revenue_series = self.build_revenue_series(restaurant, period, blueprint=series_blueprint)
        previous_revenue_series = self.build_revenue_series(
            restaurant,
            previous_period,
            blueprint=series_blueprint,
        )
        top_items = self.build_top_items(restaurant, period, limit=self.overview_top_item_limit)
        waiters = self.get_role_breakdown_rows(restaurant, period, role='waiter')[: self.overview_staff_limit]
        cashiers = self.get_role_breakdown_rows(restaurant, period, role='cashier')[: self.overview_staff_limit]
        payment_method_breakdown = self.build_choice_breakdown(
            list(get_payment_breakdown_report_queryset(restaurant, period)),
            Payment.Method.choices,
            total_sales=self.get_safe_number(current_summary.get('sales_total')),
        )
        channel_breakdown = self.build_choice_breakdown(
            list(self.get_channel_breakdown_queryset(restaurant, period)),
            Order.Channel.choices,
            total_sales=self.get_safe_number(current_summary.get('sales_total')),
        )
        open_checks_rows = self.build_open_checks_rows(
            restaurant,
            period,
            limit=self.overview_open_checks_limit,
        )
        shift_rows = self.build_shift_rows(restaurant, period, limit=self.overview_shift_limit)
        all_shift_rows = self.build_shift_rows(restaurant, period)

        return {
            'generated_at': tashkent_now(),
            'restaurant': {
                'id': restaurant.id,
                'name': restaurant.name,
                'currency': restaurant.currency,
                'address': restaurant.address,
            },
            'period': self.build_period_metadata(period, previous_period),
            'summary': {
                'sales_total': self.get_safe_number(current_summary.get('sales_total')),
                'orders_count': self.get_safe_number(current_summary.get('orders_count')),
                'average_check': self.get_safe_number(current_summary.get('average_check')),
                'open_checks': self.get_safe_number(current_summary.get('open_checks')),
                'active_tables': self.get_safe_number(current_summary.get('active_tables')),
            },
            'summary_delta': self.build_summary_delta(current_summary, previous_summary),
            'spotlight': {
                'top_item': top_items[0] if top_items else None,
                'top_waiter': waiters[0] if waiters else None,
                'top_cashier': cashiers[0] if cashiers else None,
                'top_channel': max(
                    channel_breakdown,
                    key=lambda row: (row['sales_total'], row['orders_count']),
                )
                if channel_breakdown
                else None,
                'top_payment_method': max(
                    payment_method_breakdown,
                    key=lambda row: (row['sales_total'], row['orders_count']),
                )
                if payment_method_breakdown
                else None,
                'peak_time_bucket': self.get_peak_time_bucket(revenue_series),
            },
            'revenue_series': revenue_series,
            'previous_revenue_series': previous_revenue_series,
            'top_items': top_items,
            'staff_breakdown': {
                'waiters': waiters,
                'cashiers': cashiers,
            },
            'payment_method_breakdown': payment_method_breakdown,
            'channel_breakdown': channel_breakdown,
            'open_checks_snapshot': {
                'count': self.get_safe_number(current_summary.get('open_checks')),
                'active_tables': self.get_safe_number(current_summary.get('active_tables')),
                'rows': open_checks_rows,
            },
            'cash_shift_snapshot': {
                'open_count': sum(1 for row in all_shift_rows if row['status'] == 'open'),
                'difference_count': sum(1 for row in all_shift_rows if row['is_difference']),
                'cash_total': sum(row['cash_total'] for row in all_shift_rows),
                'card_total': sum(row['card_total'] for row in all_shift_rows),
                'qr_total': sum(row['qr_total'] for row in all_shift_rows),
                'refund_total': sum(row['refund_total'] for row in all_shift_rows),
                'receipt_count': sum(row['receipt_count'] for row in all_shift_rows),
                'rows': shift_rows,
            },
        }


class OwnerDashboardDetailService(OwnerDashboardBaseService):
    def build_open_checks_queryset(self, *, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_open_checks_queryset(restaurant, period)

    def build_top_items_queryset(self, *, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_top_items_queryset(restaurant, period)

    def build_staff_queryset(self, *, restaurant, period: ReportPeriod, role: str) -> QuerySet:
        return self.get_cashier_queryset(restaurant, period) if role == 'cashier' else self.get_waiter_queryset(restaurant, period)

    def build_shift_queryset(self, *, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_shift_queryset(restaurant, period)
