from django.db.models import Count, F, IntegerField, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from apps.billing.helpers import get_payment_model
from apps.floor.models import TableSession
from apps.reporting.services import (
    ReportPeriod,
    build_summary_payload,
    get_open_checks_report_queryset,
    get_shift_report_queryset,
    get_top_items_report_queryset,
)
from apps.sales.helpers import get_order_model

Order = get_order_model()
Payment = get_payment_model()

STAFF_ROLE_GROUPS = {
    "waiter": ("waiter",),
    "cashier": ("cashier", "fast_food_cashier"),
    "manager": ("manager", "fast_food_manager"),
}


class OwnerDashboardQueryMixin:
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
            "-revenue", "-quantity", "catalog_item_name"
        )

    def get_waiter_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_staff_item_creator_queryset(
            restaurant, period, role="waiter"
        ).order_by("-sales_total", "-orders_count", "user_name")

    def get_cashier_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_staff_item_creator_queryset(
            restaurant, period, role="cashier"
        ).order_by("-sales_total", "-orders_count", "user_name")

    def get_manager_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return self.get_staff_item_creator_queryset(
            restaurant, period, role="manager"
        ).order_by("-sales_total", "-orders_count", "user_name")

    def get_staff_item_creator_queryset(
        self, restaurant, period: ReportPeriod, *, role: str | None = None
    ) -> QuerySet:
        from apps.sales.helpers import get_order_item_model

        OrderItem = get_order_item_model()
        queryset = OrderItem.objects.filter(
            order__created_at__gte=period.start,
            order__created_at__lt=period.end,
        ).exclude(status=OrderItem.Status.CANCELLED)
        if restaurant is not None:
            queryset = queryset.filter(order__restaurant=restaurant)
        if role:
            queryset = queryset.filter(
                created_by__role__code__in=STAFF_ROLE_GROUPS.get(role, ())
            )
        return queryset.values(
            user_id=F("created_by__id"),
            user_name=F("created_by__full_name"),
        ).annotate(
            orders_count=Count("order_id", distinct=True),
            items_count=Coalesce(
                Sum("quantity"), Value(0), output_field=IntegerField()
            ),
            sales_total=Coalesce(
                Sum("line_total"), Value(0), output_field=IntegerField()
            ),
        )

    def get_channel_breakdown_queryset(
        self, restaurant, period: ReportPeriod
    ) -> QuerySet:
        return (
            self.get_closed_orders_queryset(restaurant, period)
            .values(code=F("channel"))
            .annotate(
                orders_count=Count("id"),
                sales_total=Coalesce(
                    Sum("total"), Value(0), output_field=IntegerField()
                ),
            )
            .order_by("-sales_total", "code")
        )

    def get_open_checks_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_open_checks_report_queryset(restaurant, period).order_by(
            "-created_at", "-order_number"
        )

    def get_active_tables_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return TableSession.objects.filter(
            restaurant=restaurant,
            created_at__gte=period.start,
            created_at__lt=period.end,
            status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT],
        )

    def build_dashboard_summary(self, restaurant, period: ReportPeriod) -> dict:
        summary = build_summary_payload(restaurant, period)
        return {
            **summary,
            "open_checks": self.get_open_checks_queryset(restaurant, period).count(),
            "active_tables": self.get_active_tables_queryset(
                restaurant, period
            ).count(),
        }

    def get_shift_queryset(self, restaurant, period: ReportPeriod) -> QuerySet:
        return get_shift_report_queryset(restaurant, period).order_by("-opened_at")
