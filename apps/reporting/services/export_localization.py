from collections.abc import Sequence

from django.utils.translation import gettext as _

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.sales.helpers import get_order_model

from apps.reporting.selectors.reporting import (
    REPORT_PERIOD_DAY,
    REPORT_PERIOD_MONTH,
    REPORT_PERIOD_RANGE,
    REPORT_PERIOD_YEAR,
    ReportPeriod,
)

Order = get_order_model()
Payment = get_payment_model()
Receipt = get_receipt_model()

REPORT_TITLE_SUMMARY = 'summary'
REPORT_TITLE_SALES = 'sales'
REPORT_TITLE_OPEN_CHECKS = 'open_checks'
REPORT_TITLE_RECEIPTS = 'receipts'
REPORT_TITLE_TOP_ITEMS = 'top_items'
REPORT_TITLE_TOP_STAFF = 'top_staff'
REPORT_TITLE_PAYMENT_BREAKDOWN = 'payment_breakdown'
REPORT_TITLE_SHIFTS = 'shifts'


def get_report_title(report_key: str) -> str:
    titles = {
        REPORT_TITLE_SUMMARY: _('Summary Report'),
        REPORT_TITLE_SALES: _('Sales Report'),
        REPORT_TITLE_OPEN_CHECKS: _('Open Checks Report'),
        REPORT_TITLE_RECEIPTS: _('Receipts Report'),
        REPORT_TITLE_TOP_ITEMS: _('Top Items Report'),
        REPORT_TITLE_TOP_STAFF: _('Top Staff Report'),
        REPORT_TITLE_PAYMENT_BREAKDOWN: _('Payment Breakdown Report'),
        REPORT_TITLE_SHIFTS: _('Shift Report'),
    }
    return titles[report_key]


def get_report_export_filename(report_key: str, period: ReportPeriod) -> str:
    report_names = {
        REPORT_TITLE_SUMMARY: _('summary-report'),
        REPORT_TITLE_SALES: _('sales-report'),
        REPORT_TITLE_OPEN_CHECKS: _('open-checks-report'),
        REPORT_TITLE_RECEIPTS: _('receipts-report'),
        REPORT_TITLE_TOP_ITEMS: _('top-items-report'),
        REPORT_TITLE_TOP_STAFF: _('top-staff-report'),
        REPORT_TITLE_PAYMENT_BREAKDOWN: _('payment-breakdown-report'),
        REPORT_TITLE_SHIFTS: _('shift-report'),
    }
    period_names = {
        REPORT_PERIOD_DAY: _('day'),
        REPORT_PERIOD_MONTH: _('month'),
        REPORT_PERIOD_RANGE: _('range'),
        REPORT_PERIOD_YEAR: _('year'),
    }
    period_value = period.value.replace(' - ', '-')
    return f'{report_names[report_key]}-{period_names[period.period_type]}-{period_value}.xlsx'


def get_report_section_title(report_key: str) -> str:
    section_titles = {
        REPORT_TITLE_SALES: _('Sales By Method'),
        REPORT_TITLE_OPEN_CHECKS: _('Open Checks'),
        REPORT_TITLE_PAYMENT_BREAKDOWN: _('Payment Breakdown'),
    }
    return section_titles[report_key]


def get_summary_metrics(summary: dict) -> list[tuple[str, object]]:
    return [
        (_('Gross Sales Total'), summary['gross_sales_total']),
        (_('Refunds Total'), summary['refunds_total']),
        (_('Sales Total'), summary['sales_total']),
        (_('Orders Count'), summary['orders_count']),
        (_('Average Check'), summary['average_check']),
        (_('Prechecks'), summary['prechecks_count']),
        (_('Receipts'), summary['receipts_count']),
    ]


def get_sales_columns() -> list[tuple[str, str]]:
    return [('method', _('Method')), ('count', _('Count')), ('total', _('Total'))]


def get_open_checks_columns() -> list[tuple[str, str]]:
    return [
        ('order_number', _('Order')),
        ('status', _('Status')),
        ('hall_name', _('Hall')),
        ('table_name', _('Table')),
        ('total', _('Total')),
        ('created_at', _('Created At')),
    ]


def get_top_items_columns() -> list[tuple[str, str]]:
    return [
        ('catalog_item_name', _('Item')),
        ('category_name', _('Category')),
        ('quantity', _('Quantity')),
        ('revenue', _('Revenue')),
    ]


def get_top_staff_columns() -> list[tuple[str, str]]:
    return [
        ('staff_name', _('Staff')),
        ('order_count', _('Orders')),
        ('items_count', _('Items')),
        ('total_sales', _('Total Sales')),
    ]


def get_shift_columns() -> list[tuple[str, str]]:
    return [
        ('cashier_name', _('Cashier')),
        ('cash_desk_name', _('Cash Desk')),
        ('status', _('Status')),
        ('opened_at', _('Opened At')),
        ('closed_at', _('Closed At')),
        ('opening_cash_amount', _('Opening Cash')),
        ('expected_closing_cash_amount', _('Expected Cash')),
        ('actual_closing_cash_amount', _('Actual Cash')),
        ('cash_difference_amount', _('Difference')),
        ('cash_total', _('Cash Total')),
        ('card_total', _('Card Total')),
        ('refund_total', _('Refund Total')),
        ('precheck_count', _('Prechecks')),
        ('receipt_count', _('Receipts')),
        ('id', _('Shift')),
    ]


def get_receipts_columns() -> list[tuple[str, str]]:
    return [
        ('order_number', _('Order')),
        ('kind', _('Type')),
        ('status', _('Status')),
        ('amount', _('Amount')),
        ('payment_method', _('Payment method')),
        ('cashier_name', _('Cashier')),
        ('cash_desk_name', _('Cash Desk')),
        ('created_at', _('Created At')),
    ]


def build_report_filter_pairs(
    period: ReportPeriod,
    extra_filters: Sequence[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    filters = [
        (_('Period'), get_report_period_type_label(period.period_type)),
        (_('Value'), period.label),
    ]
    for key, value in extra_filters or ():
        if value in (None, ''):
            continue
        filters.append((get_filter_label(key), translate_filter_value(key, value)))
    return filters


def get_report_period_type_label(period_type: str) -> str:
    labels = {
        REPORT_PERIOD_DAY: _('Day'),
        REPORT_PERIOD_MONTH: _('Month'),
        REPORT_PERIOD_RANGE: _('Range'),
        REPORT_PERIOD_YEAR: _('Year'),
    }
    return labels.get(period_type, period_type)


def get_filter_label(key: str) -> str:
    labels = {
        'payment_method': _('Payment method'),
        'status': _('Status'),
        'hall': _('Hall'),
        'category': _('Category'),
        'cash_desk': _('Cash desk'),
        'cashier': _('Cashier'),
        'difference_only': _('Difference only'),
        'search': _('Search'),
        'receipt_kind': _('Type'),
        'receipt_status': _('Status'),
    }
    return labels.get(key, key)


def translate_filter_value(key: str, value: str) -> str:
    if key == 'payment_method':
        return get_payment_method_label(value)
    if key == 'status':
        return get_order_status_label(value)
    if key == 'receipt_kind':
        return get_receipt_kind_label(value)
    if key == 'receipt_status':
        return get_receipt_status_label(value)
    if key == 'difference_only':
        return _('Yes') if value.lower() in {'1', 'true', 'yes'} else _('No')
    return value


def localize_sales_rows(rows: Sequence[dict]) -> list[dict]:
    return [{**row, 'method': get_payment_method_label(row.get('method'))} for row in rows]


def localize_open_checks_rows(rows: Sequence[dict]) -> list[dict]:
    return [{**row, 'status': get_order_status_label(row.get('status'))} for row in rows]


def localize_receipt_rows(rows: Sequence[dict]) -> list[dict]:
    return [
        {
            **row,
            'kind': get_receipt_kind_label(row.get('kind')),
            'status': get_receipt_status_label(row.get('status')),
            'payment_method': get_payment_method_label(row.get('payment_method')),
        }
        for row in rows
    ]


def localize_payment_breakdown_rows(rows: Sequence[dict]) -> list[dict]:
    return localize_sales_rows(rows)


def get_payment_method_label(value: str | None) -> str:
    labels = {
        Payment.Method.CASH: _('Cash'),
        Payment.Method.CARD: _('Card'),
        Payment.Method.QR: _('QR'),
        Payment.Method.MIXED: _('Mixed'),
    }
    return labels.get(value, value or '')


def get_receipt_kind_label(value: str | None) -> str:
    labels = {
        Receipt.Kind.PLAIN: _('Precheck'),
        Receipt.Kind.FISCAL: _('Receipt'),
    }
    return labels.get(value, value or '')


def get_receipt_status_label(value: str | None) -> str:
    labels = {
        Receipt.Status.CREATED: _('Created'),
        Receipt.Status.SENT: _('Sent'),
        Receipt.Status.FAILED: _('Failed'),
    }
    return labels.get(value, value or '')


def get_order_status_label(value: str | None) -> str:
    labels = {
        Order.Status.OPEN: _('Open'),
        Order.Status.SUBMITTED: _('Submitted'),
        Order.Status.READY: _('Ready'),
        Order.Status.CLOSED: _('Closed'),
        Order.Status.CANCELLED: _('Cancelled'),
    }
    return labels.get(value, value or '')


def get_empty_value_placeholder() -> str:
    return _('No data')


def localize_shift_rows(rows: Sequence[dict]) -> list[dict]:
    return [{**row, 'status': get_order_status_label(row.get('status'))} for row in rows]
