from unittest.mock import patch

from django.test import TestCase
from django_q.models import Schedule

from apps.restaurants.models import Restaurant
from apps.telegram_reports.models import TelegramAccount, TelegramBranchSubscription, TelegramReportDelivery
from apps.telegram_reports.schedules import REPORT_SCHEDULES, ensure_report_schedules
from apps.telegram_reports.tasks import dispatch_scheduled_reports, send_scheduled_report


class FakeDeliveryClient:
    calls = []

    def send_message(self, **payload):
        self.__class__.calls.append(payload)
        return {"message_id": 991}


class TelegramReportScheduleTests(TestCase):
    def test_exact_three_cron_schedules_are_created(self):
        ensure_report_schedules()

        schedules = Schedule.objects.filter(name__startswith="telegram_reports.").order_by("name")
        self.assertEqual(schedules.count(), 3)
        self.assertEqual(
            {(item.name, item.cron) for item in schedules},
            {(name, cron) for name, _func, cron in REPORT_SCHEDULES},
        )
        self.assertTrue(all(item.schedule_type == Schedule.CRON for item in schedules))

    @patch("apps.telegram_reports.tasks.async_task")
    def test_dispatch_fans_out_one_task_per_connected_branch(self, async_task):
        account = TelegramAccount.objects.create(telegram_user_id=1, chat_id=1)
        first = Restaurant.objects.create(name="First")
        second = Restaurant.objects.create(name="Second")
        TelegramBranchSubscription.objects.create(account=account, restaurant=first)
        TelegramBranchSubscription.objects.create(account=account, restaurant=second)

        count = dispatch_scheduled_reports(TelegramReportDelivery.ReportType.DAILY)

        self.assertEqual(count, 2)
        self.assertEqual(async_task.call_count, 2)

    @patch("apps.telegram_reports.tasks.TelegramReportService.render", return_value="daily report")
    @patch("apps.telegram_reports.tasks.TelegramBotClient", FakeDeliveryClient)
    def test_delivery_is_idempotent_per_branch_and_period(self, render):
        FakeDeliveryClient.calls = []
        account = TelegramAccount.objects.create(telegram_user_id=2, chat_id=2)
        branch = Restaurant.objects.create(name="Qamish")
        subscription = TelegramBranchSubscription.objects.create(account=account, restaurant=branch)

        first = send_scheduled_report(
            str(subscription.id),
            TelegramReportDelivery.ReportType.DAILY,
            "2026-07-24",
            "2026-07-25",
        )
        second = send_scheduled_report(
            str(subscription.id),
            TelegramReportDelivery.ReportType.DAILY,
            "2026-07-24",
            "2026-07-25",
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(FakeDeliveryClient.calls), 1)
        self.assertEqual(render.call_count, 1)
        delivery = TelegramReportDelivery.objects.get()
        self.assertEqual(delivery.status, TelegramReportDelivery.Status.SENT)
        self.assertEqual(delivery.telegram_message_id, 991)
