from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from apps.billing.helpers import get_payment_model

Payment = get_payment_model()


def build_unikassa_like_report(
    *,
    source: str,
    title: str,
    rows: list[dict],
    refunds: list,
    opened_at,
    closed_at,
    terminal_id: str,
    restaurant=None,
) -> dict:
    sale_totals = _totals_by_method(rows)
    sale_tender_totals = _tender_totals(rows)
    refund_totals = _refund_tender_totals(refunds)
    sale_total = sum(sale_totals.values())
    refund_total = sum(refund_totals.values())
    fiscal_receipt_count = sum(
        int(row.get("fiscal_receipt_count") or 0) for row in rows
    )
    return {
        "ReportSource": source,
        "ReportTitle": title,
        "TerminalID": terminal_id,
        "OpenTime": _format_report_datetime(opened_at),
        "CloseTime": _format_report_datetime(closed_at),
        "TotalSaleCount": len(rows),
        "TotalRefundCount": len(refunds),
        "TotalCash": {
            "Sale": sale_tender_totals.get(Payment.Method.CASH, 0),
            "Refund": refund_totals.get(Payment.Method.CASH, 0),
        },
        "TotalCard": {
            "Sale": sale_tender_totals.get(Payment.Method.CARD, 0),
            "Refund": refund_totals.get(Payment.Method.CARD, 0),
        },
        "TotalQR": {
            "Sale": sale_tender_totals.get(Payment.Method.QR, 0),
            "Refund": refund_totals.get(Payment.Method.QR, 0),
        },
        "TotalVAT": {
            "Sale": estimate_vat(sale_total, restaurant=restaurant),
            "Refund": estimate_vat(refund_total, restaurant=restaurant),
        },
        "TotalSaleAmount": sale_total,
        "TotalRefundAmount": refund_total,
        "NetTotal": sale_total - refund_total,
        "OrdersCount": len(
            {row.get("order_id") for row in rows if row.get("order_id")}
        ),
        "PaymentsCount": len(rows),
        "FiscalReceiptCount": fiscal_receipt_count,
        "Payments": rows,
    }


def refund_tender_amounts(refund) -> dict:
    payment = getattr(refund, "payment", None)
    refund_amount = int(getattr(refund, "amount", 0) or 0)
    if payment is None or refund_amount <= 0:
        return {}
    if payment.method == Payment.Method.QR:
        return {Payment.Method.QR: refund_amount}

    payment_amount = int(getattr(payment, "amount", 0) or 0)
    cash_amount = int(getattr(payment, "cash_amount", 0) or 0)
    card_amount = int(getattr(payment, "card_amount", 0) or 0)
    if cash_amount > 0 and card_amount > 0 and payment_amount > 0:
        cash_refund = int(
            (
                Decimal(refund_amount) * Decimal(cash_amount) / Decimal(payment_amount)
            ).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        cash_refund = min(max(cash_refund, 0), refund_amount)
        return {
            Payment.Method.CASH: cash_refund,
            Payment.Method.CARD: refund_amount - cash_refund,
        }
    if cash_amount > 0:
        return {Payment.Method.CASH: refund_amount}
    if card_amount > 0:
        return {Payment.Method.CARD: refund_amount}
    if payment.method == Payment.Method.CASH:
        return {Payment.Method.CASH: refund_amount}
    return {Payment.Method.CARD: refund_amount}


def report_terminal_id(*, cash_desk=None, payments=None) -> str:
    if cash_desk is not None and getattr(cash_desk, "terminal_id", ""):
        return str(cash_desk.terminal_id).strip()
    for payment in list(payments or []):
        payment_cash_desk = getattr(payment, "cash_desk", None)
        if payment_cash_desk is not None and getattr(
            payment_cash_desk, "terminal_id", ""
        ):
            return str(payment_cash_desk.terminal_id).strip()
    return ""


def _totals_by_method(rows: list[dict]) -> dict:
    totals = {}
    for row in rows:
        method = row.get("method") or ""
        totals[method] = totals.get(method, 0) + int(row.get("amount") or 0)
    return totals


def _tender_totals(rows: list[dict]) -> dict:
    totals = {}
    for row in rows:
        totals[Payment.Method.CASH] = totals.get(Payment.Method.CASH, 0) + int(
            row.get("cash_amount") or 0
        )
        totals[Payment.Method.CARD] = totals.get(Payment.Method.CARD, 0) + int(
            row.get("card_amount") or 0
        )
        totals[Payment.Method.QR] = totals.get(Payment.Method.QR, 0) + int(
            row.get("qr_amount") or 0
        )
    return totals


def _refund_tender_totals(refunds: list) -> dict:
    totals = {}
    for refund in refunds:
        for method, amount in refund_tender_amounts(refund).items():
            totals[method] = totals.get(method, 0) + amount
    return totals


def _format_report_datetime(value) -> str | None:
    if value is None:
        return None
    return (
        timezone.localtime(value).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    )


def estimate_vat(amount: int, *, restaurant=None) -> int:
    if not restaurant or not getattr(restaurant, "vat_enabled", False):
        return 0
    try:
        percent = Decimal(str(getattr(restaurant, "vat_percent", 0) or 0))
    except Exception:
        return 0
    if percent <= 0:
        return 0
    return int(
        (Decimal(amount) * percent / (Decimal("100") + percent)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
