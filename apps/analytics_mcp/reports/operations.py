"""Scoped operational aggregates. No customer contacts, credentials or free-text notes."""

from django.db.models import Count, F, Sum

from apps.billing.models import CashExpense, CashShift, Payment, PaymentRefund
from apps.reporting.selectors.reporting import get_shift_report_queryset
from apps.sales.models import Order, OrderItem
from ..contracts import PeriodInput, RankedInput
from ..registry import ReportDefinition


def scope_row(context, restaurant_id):
    return {"branch_id": str(restaurant_id)} if len(context.branches) > 1 else {}


def expense_summary(context, params):
    rows = CashExpense.objects.filter(
        restaurant__in=context.branches,
        status=CashExpense.Status.POSTED,
        occurred_at__gte=context.period.start,
        occurred_at__lt=context.period.end,
    )
    total = rows.aggregate(amount=Sum("amount"), count=Count("pk"))
    categories = (
        rows.values("category_name_snapshot")
        .annotate(amount=Sum("amount"), count=Count("pk"))
        .order_by("-amount", "category_name_snapshot")
    )
    data = [
        {
            "category": row["category_name_snapshot"],
            "amount": row["amount"],
            "count": row["count"],
        }
        for row in categories[: params.limit]
    ]
    context.warnings.append(
        "Posted cash expenses only; voided expenses are excluded. This is not a complete profit-and-loss statement."
    )
    return {
        "total_expenses": total["amount"] or 0,
        "expense_count": total["count"],
        "categories": data,
        "category_count": categories.count(),
        "limit": params.limit,
    }


def staff_performance(context, params):
    items = OrderItem.objects.filter(
        order__restaurant__in=context.branches,
        order__status=Order.Status.CLOSED,
        order__closed_at__gte=context.period.start,
        order__closed_at__lt=context.period.end,
    ).exclude(status=OrderItem.Status.CANCELLED)
    grouped = (
        items.values("order__restaurant_id", "created_by_id", "created_by__full_name")
        .annotate(
            revenue=Sum("line_total"), orders_count=Count("order_id", distinct=True)
        )
        .order_by("-revenue", "created_by_id")
    )
    count = grouped.count()
    rows = [
        {
            **scope_row(context, row["order__restaurant_id"]),
            "staff_id": str(row["created_by_id"]) if row["created_by_id"] else None,
            "name": row["created_by__full_name"] or "Noma’lum",
            "line_revenue": row["revenue"] or 0,
            "orders_count": row["orders_count"],
        }
        for row in grouped[: params.limit]
    ]
    context.warnings.append(
        "Sales are attributed to the employee who added each item, not the cashier or assigned waiter. One order can count for several employees; do not sum their order counts. Refunds are not allocated. This is sales activity, not an overall employee assessment."
    )
    return {
        "staff": rows,
        "staff_count": count,
        "limit": params.limit,
        "total_line_revenue": items.aggregate(value=Sum("line_total"))["value"] or 0,
    }


def table_performance(context, params):
    orders = Order.objects.filter(
        restaurant__in=context.branches,
        status=Order.Status.CLOSED,
        closed_at__gte=context.period.start,
        closed_at__lt=context.period.end,
        table_session__isnull=False,
    )
    grouped = (
        orders.values(
            "restaurant_id",
            "table_session__table_id",
            "table_session__table__name",
            "table_session__hall__name",
        )
        .annotate(
            order_total=Sum("total"),
            orders_count=Count("pk"),
            guests=Sum("guest_count"),
        )
        .order_by("-order_total", "table_session__table_id")
    )
    rows = [
        {
            **scope_row(context, row["restaurant_id"]),
            "table_id": str(row["table_session__table_id"]),
            "table": row["table_session__table__name"],
            "hall": row["table_session__hall__name"],
            "order_total": row["order_total"] or 0,
            "orders_count": row["orders_count"],
            "guests_on_orders": row["guests"] or 0,
            "average_order": (row["order_total"] or 0) // row["orders_count"],
        }
        for row in grouped[: params.limit]
    ]
    context.warnings.append(
        "Closed-order totals are attributed to the current primary table of the session. Moved or merged tables have no historical revenue split. Guest counts are per order, not unique visitors; order totals are not refund-adjusted receipts."
    )
    totals = orders.aggregate(order_total=Sum("total"), orders_count=Count("pk"))
    totals["order_total"] = totals["order_total"] or 0
    return {
        "tables": rows,
        "table_count": grouped.count(),
        "limit": params.limit,
        "totals": totals,
    }


def payment_breakdown(context, params):
    payments = Payment.objects.filter(
        order__restaurant__in=context.branches,
        status=Payment.Status.SUCCEEDED,
        paid_at__gte=context.period.start,
        paid_at__lt=context.period.end,
    )
    refunds = PaymentRefund.objects.filter(
        payment__order__restaurant__in=context.branches,
        status=PaymentRefund.Status.SUCCEEDED,
        refunded_at__gte=context.period.start,
        refunded_at__lt=context.period.end,
    )
    gross = {
        r["method"]: r
        for r in payments.values("method").annotate(
            amount=Sum("amount"), count=Count("pk")
        )
    }
    returned = {
        r["payment__method"]: r["amount"]
        for r in refunds.values("payment__method").annotate(amount=Sum("amount"))
    }
    rows = []
    for method, label in Payment.Method.choices:
        paid = gross.get(method, {}).get("amount", 0)
        refund = returned.get(method, 0)
        rows.append(
            {
                "method": method,
                "gross_receipts": paid,
                "refunds": refund,
                "net_receipts": paid - refund,
                "payments_count": gross.get(method, {}).get("count", 0),
            }
        )
    context.warnings.append(
        "Mixed payments remain a separate method. Refunds follow their own refund date and the original payment method; this is not a cash-drawer reconciliation."
    )
    return {
        "methods": rows,
        "totals": {
            key: sum(row[key] for row in rows)
            for key in ("gross_receipts", "refunds", "net_receipts", "payments_count")
        },
    }


def shift_summary(context, params):
    shifts = CashShift.objects.filter(
        cash_desk__restaurant__in=context.branches,
        opened_at__gte=context.period.start,
        opened_at__lt=context.period.end,
    )
    count = shifts.count()
    selected = (
        get_shift_report_queryset(context.branches, context.period)
        .annotate(branch_id=F("cash_desk__restaurant_id"))
        .order_by("-opened_at", "id")[: params.limit]
    )
    fields = (
        "status",
        "opening_cash_amount",
        "actual_closing_cash_amount",
        "expected_closing_cash_amount",
        "cash_difference_amount",
        "cash_total",
        "card_total",
        "qr_total",
        "refund_total",
        "expense_total",
        "receipt_count",
    )
    rows = []
    for row in selected:
        rows.append(
            {
                **scope_row(context, row["branch_id"]),
                "shift_id": str(row["id"]),
                "cash_desk": row["cash_desk_name"],
                "opened_at": row["opened_at"].isoformat(),
                "closed_at": row["closed_at"].isoformat() if row["closed_at"] else None,
                **{key: row[key] for key in fields},
            }
        )
    context.warnings.append(
        "Shifts are selected by opening date. Values cover each entire shift, including activity outside the selected period; open shifts are provisional. Compare daily receipts with get_sales_summary instead."
    )
    return {
        "shifts": rows,
        "shift_count": count,
        "limit": params.limit,
        "open_count": shifts.filter(status=CashShift.Status.OPEN).count(),
    }


REPORTS = (
    ReportDefinition(
        "get_expenses",
        "Xarajatlar",
        "Read posted cash expenses and top categories. Excludes voided entries and personal recipient details; not profit.",
        RankedInput,
        expense_summary,
        permission="expenses.view",
        metric_basis={"expenses": "posted CashExpense.amount by occurred_at"},
    ),
    ReportDefinition(
        "get_staff_performance",
        "Xodimlar savdosi",
        "Read closed-order item revenue attributed to item creator. Not cashier totals or an employee quality assessment.",
        RankedInput,
        staff_performance,
        permission="reports.view",
        metric_basis={
            "revenue": "non-cancelled line_total on CLOSED orders by closed_at and item creator"
        },
    ),
    ReportDefinition(
        "get_table_performance",
        "Stollar statistikasi",
        "Rank primary tables by closed-order total; includes hall and order counts. Moved/merged sessions use current primary table.",
        RankedInput,
        table_performance,
        permission="reports.view",
        metric_basis={
            "revenue": "CLOSED Order.total by closed_at; current primary session table; not refund-adjusted"
        },
    ),
    ReportDefinition(
        "get_payment_breakdown",
        "To‘lov turlari",
        "Read gross receipts, refunds and net receipts by cash/card/QR/mixed method over the selected period.",
        PeriodInput,
        payment_breakdown,
        permission="reports.view",
        metric_basis={
            "gross": "succeeded payments by paid_at",
            "refunds": "succeeded refunds by refunded_at and original payment method",
        },
    ),
    ReportDefinition(
        "get_cash_shifts",
        "Kassa smenalari",
        "Read latest cash shifts opened during the period, their recorded totals, expenses and closing differences. A shift may span several dates.",
        RankedInput,
        shift_summary,
        permission="reports.view",
        metric_basis={
            "selection": "CashShift.opened_at",
            "totals": "persisted whole-shift accounting totals, not a period cash-flow report",
        },
    ),
)
