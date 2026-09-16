from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncHour

from apps.billing.helpers import (
    get_payment_model,
    get_payment_refund_model,
    get_receipt_model,
)
from apps.reporting.selectors.reporting import (
    build_summary_payload,
    get_top_items_report_queryset,
)
from apps.reporting.services import ReportPeriod
from apps.reporting.services.common_report import CommonReportService
from apps.sales.helpers import get_order_model
from common.utils.date import TASHKENT_TIMEZONE

from ..contracts import (
    BranchInput,
    PeriodInput,
    SeriesInput,
    SummaryInput,
    TopProductsInput,
)
from ..policy import AnalyticsError
from ..registry import ReportDefinition

Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Order = get_order_model()
Receipt = get_receipt_model()
SALES_BASIS = {
    "gross_sales_total": "SUCCEEDED payments by paid_at",
    "refunds_total": "SUCCEEDED refunds by refunded_at",
    "sales_total": "gross_sales_total minus refunds_total; not profit",
    "orders_count": "non-cancelled orders by closed_at",
    "average_check": "net receipts divided by closed orders (integer floor); zero when no closed orders",
}


def list_branches(context, params):
    if len(context.branches) == 1:
        return {"restaurant": context.branch_metadata[0], "show_branches": False}
    return {"branches": context.branch_metadata}


def sales_summary(context, params):
    summary = build_summary_payload(context.branches, context.period)
    result = {"summary": summary}
    if params.compare_previous:
        # Shift by whole calendar days but retain the current partial-day cutoff.
        day_span = (context.end_date - context.start_date).days + 1
        offset = timedelta(days=day_span)
        previous = ReportPeriod(
            "range",
            context.period.start - offset,
            context.period.end - offset,
            "",
            "",
            "",
        )
        previous_summary = build_summary_payload(context.branches, previous)
        result.update(
            {
                "previous_summary": previous_summary,
                "comparison": CommonReportService().build_comparisons(
                    summary, previous_summary
                ),
                "comparison_period": {
                    "start_inclusive": previous.start.isoformat(),
                    "end_exclusive": previous.end.isoformat(),
                    "basis": "preceding equal calendar span with matching elapsed cutoff",
                },
            }
        )
    return result


def sales_timeseries(context, params):
    if params.granularity == "hour" and context.start_date != context.end_date:
        raise AnalyticsError(
            "invalid_period", "Hourly charts support a single calendar day."
        )
    ids = [r.pk for r in context.branches]
    period = context.period
    trunc = TruncHour if params.granularity == "hour" else TruncDate

    def grouped(queryset, field, aggregate):
        return {
            row["bucket"]: row["value"] or 0
            for row in queryset.annotate(
                bucket=trunc(field, tzinfo=TASHKENT_TIMEZONE),
            )
            .values("bucket")
            .annotate(value=aggregate)
        }

    gross = grouped(
        Payment.objects.filter(
            order__restaurant_id__in=ids,
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=period.start,
            paid_at__lt=period.end,
        ),
        "paid_at",
        Sum("amount"),
    )
    refunds = grouped(
        PaymentRefund.objects.filter(
            payment__order__restaurant_id__in=ids,
            status=PaymentRefund.Status.SUCCEEDED,
            refunded_at__gte=period.start,
            refunded_at__lt=period.end,
        ),
        "refunded_at",
        Sum("amount"),
    )
    orders = grouped(
        Order.objects.filter(
            restaurant_id__in=ids,
            closed_at__gte=period.start,
            closed_at__lt=period.end,
        ).exclude(status=Order.Status.CANCELLED),
        "closed_at",
        Count("pk"),
    )
    cursor = period.start if params.granularity == "hour" else context.start_date
    step = timedelta(hours=1) if params.granularity == "hour" else timedelta(days=1)
    rows = []
    while (
        cursor < period.end
        if params.granularity == "hour"
        else cursor <= context.end_date
    ):
        net = gross.get(cursor, 0) - refunds.get(cursor, 0)
        count = orders.get(cursor, 0)
        rows.append(
            {
                "date": cursor.isoformat(),
                "gross_sales_total": gross.get(cursor, 0),
                "refunds_total": refunds.get(cursor, 0),
                "sales_total": net,
                "orders_count": count,
                "average_check": net // count if count else 0,
            }
        )
        cursor += step
    return {
        "granularity": params.granularity,
        "points": rows,
        "totals": {
            key: sum(row[key] for row in rows)
            for key in (
                "gross_sales_total",
                "refunds_total",
                "sales_total",
                "orders_count",
            )
        },
    }


def top_products(context, params):
    queryset = get_top_items_report_queryset(context.branches, context.period)
    if params.sale_unit:
        queryset = queryset.filter(sale_unit=params.sale_unit)
    order = (
        ("-quantity", "-revenue", "catalog_item_name")
        if params.sort_by == "quantity"
        else ("-revenue", "-quantity", "catalog_item_name")
    )
    rows = [
        {
            "name": row["catalog_item_name"],
            "category": row["category_name"],
            "sale_unit": row["sale_unit"],
            "item_type": row["item_type"],
            "quantity": CommonReportService._json_quantity(row["quantity"]),
            "revenue": int(row["revenue"] or 0),
        }
        for row in queryset.order_by(*order)[: params.limit]
    ]
    context.warnings.append(
        "Product revenue is closed-order line totals, before allocating payment refunds; it is not net cash receipts."
    )
    if len(context.branches) > 1:
        context.warnings.append(
            "Products across branches are grouped by name, category, type and sale unit; equal names may not be the same SKU."
        )
    return {
        "sort_by": params.sort_by,
        "products": rows,
        "grouping": "name_category_type_sale_unit",
    }


def compare_branches(context, params):
    if len(context.branches) < 2:
        from ..policy import AnalyticsError

        raise AnalyticsError(
            "single_restaurant",
            "Only one restaurant is available. Use get_sales_summary; do not show a branch comparison.",
        )
    # Four grouped queries regardless of branch count, with each currency preserved.
    ids = [branch.pk for branch in context.branches]
    period = context.period

    def amounts(queryset, branch_field):
        return {
            row[branch_field]: row["total"] or 0
            for row in queryset.values(branch_field).annotate(total=Sum("amount"))
        }

    gross = amounts(
        Payment.objects.filter(
            order__restaurant_id__in=ids,
            status=Payment.Status.SUCCEEDED,
            paid_at__gte=period.start,
            paid_at__lt=period.end,
        ),
        "order__restaurant_id",
    )
    refunds = amounts(
        PaymentRefund.objects.filter(
            payment__order__restaurant_id__in=ids,
            status=PaymentRefund.Status.SUCCEEDED,
            refunded_at__gte=period.start,
            refunded_at__lt=period.end,
        ),
        "payment__order__restaurant_id",
    )
    orders = {
        row["restaurant_id"]: row["count"]
        for row in Order.objects.filter(
            restaurant_id__in=ids, closed_at__gte=period.start, closed_at__lt=period.end
        )
        .exclude(status=Order.Status.CANCELLED)
        .values("restaurant_id")
        .annotate(count=Count("pk"))
    }
    receipts = {
        row["order__restaurant_id"]: row
        for row in Receipt.objects.filter(
            order__restaurant_id__in=ids,
            created_at__gte=period.start,
            created_at__lt=period.end,
            kind__in=[Receipt.Kind.PLAIN, Receipt.Kind.FISCAL],
        )
        .values("order__restaurant_id")
        .annotate(
            prechecks_count=Count("pk", filter=Q(kind=Receipt.Kind.PLAIN)),
            receipts_count=Count("pk", filter=Q(kind=Receipt.Kind.FISCAL)),
        )
    }
    rows = []
    for branch in context.branches:
        net = gross.get(branch.pk, 0) - refunds.get(branch.pk, 0)
        count = orders.get(branch.pk, 0)
        receipt = receipts.get(branch.pk, {})
        rows.append(
            {
                "branch_id": str(branch.pk),
                "name": branch.name,
                "currency": branch.currency,
                "gross_sales_total": gross.get(branch.pk, 0),
                "refunds_total": refunds.get(branch.pk, 0),
                "sales_total": net,
                "orders_count": count,
                "average_check": net // count if count else 0,
                "prechecks_count": receipt.get("prechecks_count", 0),
                "receipts_count": receipt.get("receipts_count", 0),
            }
        )
    return {"branches": rows}


REPORTS = (
    ReportDefinition(
        "list_branches",
        "Filiallarim",
        "List branches the signed-in owner has consented to and may currently access. Use IDs for subsequent reports; ask to disambiguate duplicate names.",
        BranchInput,
        list_branches,
        persist=False,
        requires_single_currency=False,
        max_branches=None,
    ),
    ReportDefinition(
        "get_sales_summary",
        "Savdo statistikasi",
        "Read gross receipts, refunds, net receipts, closed orders and average check. Today is partial in Asia/Tashkent. Optional preceding-period comparison uses the same elapsed cutoff.",
        SummaryInput,
        sales_summary,
        metric_basis=SALES_BASIS,
    ),
    ReportDefinition(
        "get_sales_timeseries",
        "Savdo grafigi ma’lumotlari",
        "Get daily or single-day hourly gross/refund/net sales points. last_7_days includes today and six earlier days. Call render_sales_chart with the returned report_id to show a graph.",
        SeriesInput,
        sales_timeseries,
        metric_basis=SALES_BASIS,
    ),
    ReportDefinition(
        "get_top_products",
        "Top mahsulotlar",
        "Rank closed-order products by line revenue or quantity. Quantity ranking requires a single sale_unit. Not refund-adjusted product profit.",
        TopProductsInput,
        top_products,
        metric_basis={
            "revenue": "non-cancelled line_total on CLOSED orders by closed_at; no refund allocation",
            "quantity": "sold quantity in the displayed sale_unit",
        },
    ),
    ReportDefinition(
        "compare_branches",
        "Filiallarni taqqoslash",
        "Compare authorized branches over the same period. Each row keeps its currency; do not sum or rank different currencies together.",
        PeriodInput,
        compare_branches,
        requires_single_currency=False,
        metric_basis=SALES_BASIS,
    ),
)
