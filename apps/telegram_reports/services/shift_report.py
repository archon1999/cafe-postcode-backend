from common.sale_units import sale_unit_label

from django.template.loader import render_to_string
from django.utils import timezone

from apps.telegram_reports.formatters import format_pos_money, format_quantity


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _money(value):
    return int(value or 0)


def _report_amount(report, group, side):
    return _money(_mapping(report.get(group)).get(side))


def _receipt_range(report):
    payments = report.get('Payments')
    payments = payments if isinstance(payments, list) else []
    order_numbers = [
        str(row.get('order_number'))
        for row in payments
        if isinstance(row, dict) and row.get('order_number') is not None
    ]
    first = report.get('FirstReceiptSeq')
    last = report.get('LastReceiptSeq')
    return (
        str(first) if first is not None else order_numbers[0] if order_numbers else '',
        str(last) if last is not None else order_numbers[-1] if order_numbers else '',
    )


def render_shift_report(shift):
    payload = _mapping(shift.close_report_payload)
    report = _mapping(_mapping(payload.get('report')).get('pos_report'))
    snapshot = _mapping(payload.get('snapshot'))
    first_receipt, last_receipt = _receipt_range(report)

    cash_precheck = _report_amount(report, 'TotalCash', 'Precheck')
    cash_receipt = _report_amount(report, 'TotalCash', 'Receipt')
    card_precheck = _report_amount(report, 'TotalCard', 'Precheck')
    card_receipt = _report_amount(report, 'TotalCard', 'Receipt')
    qr_sale = _report_amount(report, 'TotalQR', 'Sale')
    vat_sale = _report_amount(report, 'TotalVAT', 'Sale')
    cash_refund = _report_amount(report, 'TotalCash', 'Refund')
    card_refund = _report_amount(report, 'TotalCard', 'Refund')
    qr_refund = _report_amount(report, 'TotalQR', 'Refund')
    vat_refund = _report_amount(report, 'TotalVAT', 'Refund')
    total_sale = _money(
        report.get('TotalSaleAmount', cash_precheck + cash_receipt + card_precheck + card_receipt + qr_sale)
    )
    total_refund = _money(
        report.get('TotalRefundAmount', cash_refund + card_refund + qr_refund)
    )
    expense_total = _money(
        snapshot.get('expense_total', report.get('TotalExpenseAmount', shift.expense_total))
    )
    expected_cash = _money(
        snapshot.get('expected_closing_cash_amount', shift.expected_closing_cash_amount)
    )
    cashier = shift.cashier or shift.opened_by

    return render_to_string('telegram_reports/shift_report.html', {
        'branch_name': shift.cash_desk.restaurant.name,
        'cash_desk': shift.cash_desk.name,
        'cashier': cashier.full_name if cashier else '',
        'opened_at': timezone.localtime(shift.opened_at).strftime('%Y-%m-%d %H:%M'),
        'first_receipt': first_receipt,
        'last_receipt': last_receipt,
        'sale_count': _money(report.get('TotalSaleCount')),
        'cash_precheck': format_pos_money(cash_precheck),
        'cash_receipt': format_pos_money(cash_receipt),
        'card_precheck': format_pos_money(card_precheck),
        'card_receipt': format_pos_money(card_receipt),
        'qr_sale': format_pos_money(qr_sale),
        'show_qr_sale': qr_sale != 0,
        'vat_sale': format_pos_money(vat_sale),
        'show_vat_sale': vat_sale != 0,
        'total_sale': format_pos_money(total_sale),
        'refund_count': _money(report.get('TotalRefundCount')),
        'cash_refund': format_pos_money(cash_refund),
        'card_refund': format_pos_money(card_refund),
        'qr_refund': format_pos_money(qr_refund),
        'show_qr_refund': qr_refund != 0,
        'vat_refund': format_pos_money(vat_refund),
        'show_vat_refund': vat_refund != 0,
        'total_refund': format_pos_money(total_refund),
        'expenses': format_pos_money(expense_total),
        'expected_cash': format_pos_money(expected_cash),
        'sold_items': [dict(
            item_name=row['name'],
            formatted_revenue=format_pos_money(row['revenue']),
            formatted_quantity=format_quantity(row['quantity']),
            quantity_unit=sale_unit_label(row['sale_unit'], piece_label='ta'),
        ) for row in payload.get('sold_items', [])],
    }).strip()
