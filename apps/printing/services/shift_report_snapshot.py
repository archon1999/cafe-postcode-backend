from decimal import Decimal

from django.utils import timezone

from .print_snapshots import _local_datetime, _money


def _report_pair(value) -> tuple[int, int]:
    value = value if isinstance(value, dict) else {}
    return (_money(value.get("Sale")), _money(value.get("Refund")))


def _scale_fiscal_drive_money(value):
    number = Decimal(str(value or 0)) / Decimal("100")
    return int(number) if number == number.to_integral_value() else float(number)


def _report_total(report: dict, key: str, *, fallback, fiscal: bool):
    value = report.get(key)
    if value is None:
        return fallback
    return _scale_fiscal_drive_money(value) if fiscal else _money(value)


def build_shift_report_print_snapshot(
    *, shift, report: dict, fiscal: bool, closed: bool
) -> dict:
    restaurant = shift.cash_desk.restaurant
    report = dict(report or {})
    cash_sale, cash_refund = _report_pair(report.get("TotalCash"))
    card_sale, card_refund = _report_pair(report.get("TotalCard"))
    qr_sale, qr_refund = _report_pair(report.get("TotalQR"))
    vat_sale, vat_refund = _report_pair(report.get("TotalVAT"))
    if fiscal:
        cash_sale, cash_refund = map(
            _scale_fiscal_drive_money, (cash_sale, cash_refund)
        )
        card_sale, card_refund = map(
            _scale_fiscal_drive_money, (card_sale, card_refund)
        )
        qr_sale, qr_refund = map(_scale_fiscal_drive_money, (qr_sale, qr_refund))
        vat_sale, vat_refund = map(_scale_fiscal_drive_money, (vat_sale, vat_refund))
    total_sale = _report_total(
        report,
        "TotalSaleAmount",
        fallback=cash_sale + card_sale + qr_sale,
        fiscal=fiscal,
    )
    total_refund = _report_total(
        report,
        "TotalRefundAmount",
        fallback=cash_refund + card_refund + qr_refund,
        fiscal=fiscal,
    )
    payments = (
        report.get("Payments") if isinstance(report.get("Payments"), list) else []
    )
    order_numbers = [
        str(row.get("order_number"))
        for row in payments
        if isinstance(row, dict) and row.get("order_number")
    ]
    terminal_id = str(
        report.get("TerminalID") or shift.cash_desk.terminal_id or ""
    ).strip()
    return {
        "restaurant": {
            "name": restaurant.name,
            "legalName": restaurant.legal_name or restaurant.name,
            "taxNumber": restaurant.tax_number,
        },
        "shift": {
            "id": str(shift.id),
            "cashDeskName": shift.cash_desk.name,
            "cashierName": (
                shift.cashier.full_name
                if shift.cashier_id and shift.cashier
                else shift.opened_by.full_name
                if shift.opened_by_id and shift.opened_by
                else ""
            ),
        },
        "report": {
            "label": "Fiscal to'lovlar" if fiscal else "Umumiy hisobot",
            "terminalId": terminal_id,
            "factoryId": str(
                report.get("FactoryID") or report.get("FactoryId") or ""
            ).strip(),
            "serialNumber": str(
                report.get("SerialNumber") or report.get("SN") or ""
            ).strip(),
            "printedAt": _local_datetime(timezone.now()),
            "openedAt": str(report.get("OpenTime") or _local_datetime(shift.opened_at)),
            "closedAt": str(
                report.get("CloseTime")
                or (_local_datetime(shift.closed_at) if closed else "")
            ),
            "firstReceipt": str(
                report.get("FirstReceiptSeq")
                or (order_numbers[0] if order_numbers else "")
            ),
            "lastReceipt": str(
                report.get("LastReceiptSeq")
                or (order_numbers[-1] if order_numbers else "")
            ),
            "saleCount": _money(report.get("TotalSaleCount")),
            "refundCount": _money(report.get("TotalRefundCount")),
            "cashSale": cash_sale,
            "cardSale": card_sale,
            "qrSale": qr_sale,
            "vatSale": vat_sale if fiscal else 0,
            "totalSale": total_sale,
            "cashRefund": cash_refund,
            "cardRefund": card_refund,
            "qrRefund": qr_refund,
            "vatRefund": vat_refund if fiscal else 0,
            "totalRefund": total_refund,
        },
        "system": {"isFiscal": fiscal, "isClosing": closed},
    }
