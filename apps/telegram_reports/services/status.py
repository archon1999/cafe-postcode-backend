from django.core.exceptions import ObjectDoesNotExist
from django.template.loader import render_to_string
from django.utils import timezone

from apps.billing.models import CashShift
from apps.floor.models import TableSession
from apps.sales.models import Order
from apps.telegram_reports.formatters import format_compact_money
from common.utils.date import TASHKENT_TIMEZONE


class TelegramBranchStatusService:
    order_status_labels = {
        Order.Status.OPEN: "ochiq",
        Order.Status.SUBMITTED: "qabul qilingan",
        Order.Status.READY: "tayyor",
        Order.Status.CLOSED: "yopilgan",
        Order.Status.CANCELLED: "bekor qilingan",
    }

    def render(self, *, restaurant, today_summary: dict) -> str:
        latest_order = restaurant.orders.order_by("-created_at").first()
        open_shifts = list(
            CashShift.objects.filter(
                cash_desk__restaurant=restaurant,
                status=CashShift.Status.OPEN,
            )
            .select_related("cash_desk", "cashier", "opened_by")
            .order_by("opened_at")
        )
        open_checks = Order.objects.filter(restaurant=restaurant).exclude(
            status__in=(Order.Status.CLOSED, Order.Status.CANCELLED)
        ).count()
        active_tables = TableSession.objects.filter(
            restaurant=restaurant,
            status__in=(TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT),
        ).count()
        try:
            agent = restaurant.local_agent
        except ObjectDoesNotExist:
            agent = None

        local_now = timezone.now().astimezone(TASHKENT_TIMEZONE)
        return render_to_string(
            "telegram_reports/branch_status.html",
            {
                "branch_name": restaurant.name,
                "is_active": restaurant.is_active,
                "agent_online": bool(agent and agent.is_online()),
                "agent_last_seen": self.format_datetime(agent.last_seen_at) if agent and agent.last_seen_at else None,
                "latest_order": latest_order,
                "latest_order_status": self.order_status_labels.get(latest_order.status, latest_order.status) if latest_order else None,
                "latest_order_time": self.format_datetime(latest_order.created_at) if latest_order else None,
                "latest_order_total": format_compact_money(latest_order.total) if latest_order else None,
                "open_shifts": open_shifts,
                "open_checks": open_checks,
                "active_tables": active_tables,
                "today_sales": format_compact_money(today_summary.get("sales_total", 0)),
                "generated_at": local_now.strftime("%H:%M"),
            },
        ).strip()

    @staticmethod
    def format_datetime(value) -> str:
        return value.astimezone(TASHKENT_TIMEZONE).strftime("%d.%m.%Y %H:%M")
