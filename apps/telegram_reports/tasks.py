import logging
from datetime import date, timedelta

from django.utils import timezone
from django_q.tasks import async_task

from apps.reporting.services import CommonReportService
from apps.telegram_reports.client import TelegramAPIError, TelegramBotClient
from apps.telegram_reports.models import (
    TelegramBranchSubscription,
    TelegramReportDelivery,
)
from apps.telegram_reports.services import TelegramReportService


logger = logging.getLogger(__name__)


def dispatch_daily_reports() -> int:
    return dispatch_scheduled_reports(TelegramReportDelivery.ReportType.DAILY)


def dispatch_weekly_reports() -> int:
    return dispatch_scheduled_reports(TelegramReportDelivery.ReportType.WEEKLY)


def dispatch_monthly_reports() -> int:
    return dispatch_scheduled_reports(TelegramReportDelivery.ReportType.MONTHLY)


def dispatch_scheduled_reports(report_type: str) -> int:
    report_service = TelegramReportService()
    period = report_service.build_scheduled_period(report_type)
    period_start = period.start.date().isoformat()
    period_end = (period.end.date()).isoformat()
    subscription_ids = list(
        TelegramBranchSubscription.objects.filter(
            account__notifications_enabled=True,
        )
        .order_by("account_id", "restaurant__name")
        .values_list("id", flat=True)
    )
    for subscription_id in subscription_ids:
        async_task(
            "apps.telegram_reports.tasks.send_scheduled_report",
            str(subscription_id),
            report_type,
            period_start,
            period_end,
            task_name=f"telegram.{report_type}.{subscription_id}.{period_start}",
        )
    return len(subscription_ids)


def send_scheduled_report(
    subscription_id: str,
    report_type: str,
    period_start: str,
    period_end: str,
) -> bool:
    subscription = (
        TelegramBranchSubscription.objects.select_related("account", "restaurant")
        .filter(pk=subscription_id, account__notifications_enabled=True)
        .first()
    )
    if subscription is None:
        return False

    start_date = date.fromisoformat(period_start)
    exclusive_end_date = date.fromisoformat(period_end)
    inclusive_end_date = exclusive_end_date - timedelta(days=1)
    delivery, created = TelegramReportDelivery.objects.get_or_create(
        account=subscription.account,
        restaurant=subscription.restaurant,
        report_type=report_type,
        period_start=start_date,
        period_end=inclusive_end_date,
    )
    if not created and delivery.status != TelegramReportDelivery.Status.FAILED:
        return delivery.status == TelegramReportDelivery.Status.SENT

    delivery.status = TelegramReportDelivery.Status.PENDING
    delivery.attempts += 1
    delivery.error = ""
    delivery.save(update_fields=("status", "attempts", "error", "updated_at"))

    common = CommonReportService()
    if report_type == TelegramReportDelivery.ReportType.DAILY:
        period = common.build_day_period(start_date)
    elif report_type == TelegramReportDelivery.ReportType.MONTHLY:
        period = common.build_month_period(start_date.year, start_date.month)
    else:
        period = common.build_range_period(start_date, inclusive_end_date)

    try:
        text = TelegramReportService().render(
            restaurant=subscription.restaurant,
            report_type=report_type,
            period=period,
        )
        result = TelegramBotClient().send_message(
            chat_id=subscription.account.chat_id,
            text=text,
        )
    except TelegramAPIError as error:
        delivery.status = TelegramReportDelivery.Status.FAILED
        delivery.error = str(error)[:2000]
        delivery.save(update_fields=("status", "error", "updated_at"))
        if error.error_code == 403:
            subscription.account.notifications_enabled = False
            subscription.account.save(update_fields=("notifications_enabled", "updated_at"))
        logger.warning(
            "Telegram report delivery failed",
            extra={"delivery_id": str(delivery.id), "error_code": error.error_code},
        )
        return False

    delivery.status = TelegramReportDelivery.Status.SENT
    delivery.telegram_message_id = result.get("message_id") if isinstance(result, dict) else None
    delivery.sent_at = timezone.now()
    delivery.save(
        update_fields=("status", "telegram_message_id", "sent_at", "updated_at")
    )
    return True
