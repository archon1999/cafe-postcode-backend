from django.test import TestCase

from apps.restaurants.models import Restaurant
from apps.telegram_reports.handler import BRANCHES_BUTTON_TEXT, MAIN_KEYBOARD, TelegramUpdateHandler
from apps.telegram_reports.models import (
    TelegramAccount,
    TelegramBranchSubscription,
    TelegramReportDelivery,
)


class FakeTelegramClient:
    sent_messages = []
    callback_answers = []

    def send_message(self, **payload):
        self.__class__.sent_messages.append(payload)
        return {"message_id": len(self.__class__.sent_messages)}

    def answer_callback_query(self, callback_query_id, *, text=""):
        self.__class__.callback_answers.append((callback_query_id, text))
        return True


class FakeReportService:
    calls = []

    def build_current_period(self, report_type):
        return f"current-{report_type}"

    def render(self, *, restaurant, report_type, period):
        self.__class__.calls.append((restaurant.name, report_type, period))
        return f"{restaurant.name}: {report_type}"


class TelegramUpdateHandlerTests(TestCase):
    def setUp(self):
        FakeTelegramClient.sent_messages = []
        FakeTelegramClient.callback_answers = []
        FakeReportService.calls = []
        self.handler = TelegramUpdateHandler()
        self.handler.client_class = FakeTelegramClient
        self.branch = Restaurant.objects.create(name="Qamish", auth_code="A1b2C3")

    @staticmethod
    def message(text):
        return {
            "message": {
                "text": text,
                "from": {"id": 1234567890123, "first_name": "Ali", "language_code": "uz"},
                "chat": {"id": 1234567890123, "type": "private"},
            }
        }

    def test_connect_accepts_multiple_codes_and_uses_single_reply_button(self):
        self.handler.handle(self.message("/connect A1b2C3, X9y8Z7"))

        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertTrue(
            TelegramBranchSubscription.objects.filter(account=account, restaurant=self.branch).exists()
        )
        sent = FakeTelegramClient.sent_messages[-1]
        self.assertIn("Qamish", sent["text"])
        self.assertIn("X9y8Z7", sent["text"])
        self.assertEqual(sent["reply_markup"], MAIN_KEYBOARD)
        self.assertEqual(MAIN_KEYBOARD["keyboard"], [[{"text": BRANCHES_BUTTON_TEXT}]])

    def test_start_payload_connects_comma_separated_branch_codes(self):
        second_branch = Restaurant.objects.create(name="Chilonzor", auth_code="X9y8Z7")

        self.handler.handle(self.message("/start A1b2C3,X9y8Z7"))

        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertCountEqual(
            account.branch_subscriptions.values_list("restaurant_id", flat=True),
            [self.branch.id, second_branch.id],
        )
        sent = FakeTelegramClient.sent_messages[-1]
        self.assertIn("Qamish", sent["text"])
        self.assertIn("Chilonzor", sent["text"])
        self.assertEqual(sent["reply_markup"], MAIN_KEYBOARD)

    def test_start_payload_accepts_telegram_safe_separators(self):
        second_branch = Restaurant.objects.create(name="Chilonzor", auth_code="X9y8Z7")

        self.handler.handle(self.message("/start A1b2C3_X9y8Z7"))

        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertCountEqual(
            account.branch_subscriptions.values_list("restaurant_id", flat=True),
            [self.branch.id, second_branch.id],
        )

    def test_week_and_month_commands_send_current_reports_for_each_branch(self):
        second_branch = Restaurant.objects.create(name="Chilonzor", auth_code="X9y8Z7")
        self.handler.handle(self.message("/connect A1b2C3,X9y8Z7"))
        self.handler.report_service_class = FakeReportService

        for command, report_type in (
            ("/week", TelegramReportDelivery.ReportType.WEEKLY),
            ("/month", TelegramReportDelivery.ReportType.MONTHLY),
        ):
            FakeReportService.calls = []
            self.handler.handle(self.message(command))

            self.assertCountEqual(
                FakeReportService.calls,
                [
                    (self.branch.name, report_type, f"current-{report_type}"),
                    (second_branch.name, report_type, f"current-{report_type}"),
                ],
            )

    def test_connect_prompt_accepts_codes_in_followup_message(self):
        self.handler.handle(self.message("/connect"))
        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertEqual(account.state, TelegramAccount.State.AWAITING_CONNECT)

        self.handler.handle(self.message("A1b2C3"))

        account.refresh_from_db()
        self.assertEqual(account.state, TelegramAccount.State.IDLE)
        self.assertEqual(account.branch_subscriptions.count(), 1)

    def test_disconnect_callback_only_removes_subscription(self):
        self.handler.handle(self.message("/connect A1b2C3"))
        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        subscription = account.branch_subscriptions.get()

        self.handler.handle(
            {
                "callback_query": {
                    "id": "callback-1",
                    "data": f"disconnect:{subscription.id}",
                    "from": {"id": account.telegram_user_id, "first_name": "Ali"},
                    "message": {"chat": {"id": account.chat_id, "type": "private"}},
                }
            }
        )

        self.assertFalse(TelegramBranchSubscription.objects.filter(pk=subscription.pk).exists())
        self.assertTrue(Restaurant.objects.filter(pk=self.branch.pk).exists())
        self.assertIn(("callback-1", "Shahobcha uzildi"), FakeTelegramClient.callback_answers)
