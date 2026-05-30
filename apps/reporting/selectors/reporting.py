from dataclasses import dataclass
from datetime import date as date_cls, datetime

from django.db.models import Count, F, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date

from apps.billing.helpers import get_cash_shift_model, get_payment_model
from apps.floor.models import TableSession
from apps.sales.helpers import get_order_item_model, get_order_model
from common.api.query_params import get_str_query_param
from common.utils.date import tashkent_day_bounds, tashkent_month_bounds, tashkent_now, tashkent_year_bounds

CashShift = get_cash_shift_model()
Order = get_order_model()
OrderItem = get_order_item_model()
Payment = get_payment_model()

REPORT_PERIOD_DAY = 'day'
REPORT_PERIOD_MONTH = 'month'
REPORT_PERIOD_YEAR = 'year'
REPORT_PERIOD_RANGE = 'range'
REPORT_PERIOD_VALUES = frozenset(
    {REPORT_PERIOD_DAY, REPORT_PERIOD_MONTH, REPORT_PERIOD_YEAR, REPORT_PERIOD_RANGE}
)
PAYMENT_METHOD_VALUES = frozenset({choice for choice, _label in Payment.Method.choices})
ORDER_STATUS_VALUES = frozenset({choice for choice, _label in Order.Status.choices})
SHIFT_STATUS_VALUES = frozenset({choice for choice, _label in CashShift.Status.choices})


@dataclass(frozen=True)
class ReportPeriod:
    period_type: str
    start: datetime
    end: datetime
    value: str
    label: str
    file_label: str


def get_report_period(query_params) -> ReportPeriod:
    now = tashkent_now()
    start_date_value = get_str_query_param(query_params, 'start_date', aliases=('startDate',))
    end_date_value = get_str_query_param(query_params, 'end_date', aliases=('endDate',))
    period_type = get_str_query_param(query_params, 'period_type', aliases=('periodType',))
    if period_type not in REPORT_PERIOD_VALUES:
        period_type = REPORT_PERIOD_RANGE if start_date_value or end_date_value else REPORT_PERIOD_DAY

    if period_type == REPORT_PERIOD_RANGE:
        start_date, end_date = _resolve_range_dates(start_date_value, end_date_value, now)
        start, _ = tashkent_day_bounds(start_date)
        _, end = tashkent_day_bounds(end_date)
        value = f'{start_date.isoformat()} - {end_date.isoformat()}'
        return ReportPeriod(
            period_type=period_type,
            start=start,
            end=end,
            value=value,
            label=value,
            file_label=f'range-{start_date.isoformat()}-to-{end_date.isoformat()}',
        )

    if period_type == REPORT_PERIOD_MONTH:
        month_value = _resolve_month_value(get_str_query_param(query_params, 'month'), now)
        year, month = (int(part) for part in month_value.split('-'))
        start, end = tashkent_month_bounds(year, month)
        return ReportPeriod(
            period_type=period_type,
            start=start,
            end=end,
            value=month_value,
            label=month_value,
            file_label=f'month-{month_value}',
        )

    if period_type == REPORT_PERIOD_YEAR:
        year_value = _resolve_year_value(get_str_query_param(query_params, 'year'), now)
        year = int(year_value)
        start, end = tashkent_year_bounds(year)
        return ReportPeriod(
            period_type=period_type,
            start=start,
            end=end,
            value=year_value,
            label=year_value,
            file_label=f'year-{year_value}',
        )

    target_date = _resolve_date_value(get_str_query_param(query_params, 'date'), now)
    start, end = tashkent_day_bounds(target_date)
    date_value = target_date.isoformat()
    return ReportPeriod(
        period_type=REPORT_PERIOD_DAY,
        start=start,
        end=end,
        value=date_value,
        label=date_value,
        file_label=f'day-{date_value}',
    )


def build_summary_payload(restaurant, period: ReportPeriod) -> dict:
    succeeded_payments = Payment.objects.filter(
        status=Payment.Status.SUCCEEDED,
        paid_at__gte=period.start,
        paid_at__lt=period.end,
    )
    if restaurant is not None:
        succeeded_payments = succeeded_payments.filter(order__restaurant=restaurant)
    sales_total = succeeded_payments.aggregate(total=Sum('amount')).get('total') or 0
    closed_orders = Order.objects.filter(
        closed_at__gte=period.start,
        closed_at__lt=period.end,
    ).exclude(status=Order.Status.CANCELLED)
    if restaurant is not None:
        closed_orders = closed_orders.filter(restaurant=restaurant)
    orders_count = closed_orders.count()
    average_check = sales_total // orders_count if orders_count else 0
    open_checks = (
        Order.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
        .exclude(status__in=[Order.Status.CLOSED, Order.Status.CANCELLED])
    )
    if restaurant is not None:
        open_checks = open_checks.filter(restaurant=restaurant)
    open_checks = open_checks.count()
    active_tables = TableSession.objects.filter(
        created_at__gte=period.start,
        created_at__lt=period.end,
        status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
    )
    if restaurant is not None:
        active_tables = active_tables.filter(restaurant=restaurant)
    active_tables = active_tables.count()
    return {
        'sales_total': sales_total,
        'orders_count': orders_count,
        'average_check': average_check,
        'open_checks': open_checks,
        'active_tables': active_tables,
    }


def get_sales_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    queryset = Payment.objects.filter(
        status=Payment.Status.SUCCEEDED,
        paid_at__gte=period.start,
        paid_at__lt=period.end,
    )
    if restaurant is not None:
        queryset = queryset.filter(order__restaurant=restaurant)
    return queryset.values('method').annotate(count=Count('id'), total=Sum('amount'))


def get_open_checks_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    queryset = Order.objects.filter(created_at__gte=period.start, created_at__lt=period.end).exclude(
        status__in=[Order.Status.CLOSED, Order.Status.CANCELLED]
    )
    if restaurant is not None:
        queryset = queryset.filter(restaurant=restaurant)
    return queryset.values(
        'id',
        'order_number',
        'status',
        'total',
        'created_at',
        hall_id=F('table_session__hall_id'),
        hall_name=F('table_session__hall__name'),
        table_name=F('table_session__table__name'),
    )


def get_top_items_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    queryset = OrderItem.objects.filter(
        order__created_at__gte=period.start,
        order__created_at__lt=period.end,
    ).exclude(status=OrderItem.Status.CANCELLED)
    if restaurant is not None:
        queryset = queryset.filter(order__restaurant=restaurant)
    return queryset.values(
        'catalog_item_id',
        catalog_item_name=F('catalog_item__name'),
        category_id=F('catalog_item__category_id'),
        category_name=F('catalog_item__category__name'),
    ).annotate(quantity=Sum('quantity'), revenue=Sum('line_total'))


def get_top_staff_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    queryset = OrderItem.objects.filter(
        order__created_at__gte=period.start,
        order__created_at__lt=period.end,
    ).exclude(status=OrderItem.Status.CANCELLED)
    if restaurant is not None:
        queryset = queryset.filter(order__restaurant=restaurant)
    return queryset.values(
        staff_id=F('created_by__id'),
        staff_name=Coalesce(F('created_by__full_name'), Value("Noma'lum")),
    ).annotate(
        order_count=Count('order_id', distinct=True),
        items_count=Sum('quantity'),
        total_sales=Sum('line_total'),
    )


def get_payment_breakdown_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    return get_sales_report_queryset(restaurant, period)


def get_shift_report_queryset(restaurant, period: ReportPeriod) -> QuerySet:
    queryset = CashShift.objects.filter(opened_at__gte=period.start, opened_at__lt=period.end)
    if restaurant is not None:
        queryset = queryset.filter(cash_desk__restaurant=restaurant)
    return queryset.values(
        'id',
        'status',
        'opened_at',
        'closed_at',
        'opening_cash_amount',
        'actual_closing_cash_amount',
        'expected_closing_cash_amount',
        'cash_difference_amount',
        'cash_total',
        'card_total',
        'qr_total',
        'refund_total',
        'receipt_count',
        'reprint_count',
        'cash_desk_id',
        'cashier_id',
        'opened_by_id',
        cashier_name=Coalesce(F('cashier__full_name'), F('opened_by__full_name')),
        cash_desk_name=F('cash_desk__name'),
    )


def _resolve_date_value(raw_value: str, now: datetime) -> date_cls:
    parsed = parse_date(raw_value) if raw_value else None
    return parsed or now.date()


def _resolve_range_dates(
    start_raw_value: str,
    end_raw_value: str,
    now: datetime,
) -> tuple[date_cls, date_cls]:
    parsed_start = parse_date(start_raw_value) if start_raw_value else None
    parsed_end = parse_date(end_raw_value) if end_raw_value else None

    if parsed_start is None and parsed_end is None:
        parsed_start = now.date()
        parsed_end = parsed_start
    elif parsed_start is None:
        parsed_start = parsed_end
    elif parsed_end is None:
        parsed_end = parsed_start

    if parsed_start > parsed_end:
        parsed_start, parsed_end = parsed_end, parsed_start

    return parsed_start, parsed_end


def _resolve_month_value(raw_value: str, now: datetime) -> str:
    if raw_value:
        parts = raw_value.split('-')
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            year, month = int(parts[0]), int(parts[1])
            if 1 <= month <= 12:
                return f'{year:04d}-{month:02d}'
    return now.strftime('%Y-%m')


def _resolve_year_value(raw_value: str, now: datetime) -> str:
    if raw_value and raw_value.isdigit():
        return raw_value
    return str(now.year)
