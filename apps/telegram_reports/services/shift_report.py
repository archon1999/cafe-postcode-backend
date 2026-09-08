from common.sale_units import sale_unit_label

from django.template.loader import render_to_string
from django.utils import timezone

from apps.telegram_reports.formatters import format_compact_money, format_quantity


def render_shift_report(shift):
    payload = shift.close_report_payload
    report = payload['report']['pos_report']
    count = report['OrdersCount']
    total = report['TotalSaleAmount']
    return render_to_string('telegram_reports/shift_report.html', {
        'branch_name': shift.cash_desk.restaurant.name,
        'cash_desk': shift.cash_desk.name,
        'cashier': (shift.cashier or shift.opened_by).full_name,
        'opened_at': timezone.localtime(shift.opened_at).strftime('%d.%m.%Y %H:%M:%S'),
        'closed_at': timezone.localtime(shift.closed_at).strftime('%d.%m.%Y %H:%M:%S'),
        'sales': format_compact_money(total), 'orders': count,
        'average': format_compact_money(round(total / count) if count else 0),
        'cash': format_compact_money(shift.cash_total),
        'card': format_compact_money(shift.card_total),
        'qr': format_compact_money(shift.qr_total),
        'refunds': format_compact_money(shift.refund_total),
        'expenses': format_compact_money(shift.expense_total),
        'top_items': [dict(
            position=index, item_name=row['name'],
            formatted_revenue=format_compact_money(row['revenue']),
            formatted_quantity=format_quantity(row['quantity']),
            quantity_unit=sale_unit_label(row['sale_unit'], piece_label='ta'),
        ) for index, row in enumerate(payload.get('sold_items', []), 1)],
    }).strip()
