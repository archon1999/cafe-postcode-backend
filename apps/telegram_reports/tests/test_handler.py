from django.test import TestCase

from apps.restaurants.models import Restaurant
from apps.telegram_reports.handler import BRANCHES_BUTTON_TEXT, MAIN_KEYBOARD, TelegramUpdateHandler
from apps.telegram_reports.models import (
    TelegramAccount,
    TelegramBranchSubscription,
    TelegramLinkToken,
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
        self.branch = Restaurant.objects.create(name="Qamish")

    @staticmethod
    def message(text):
        return {
            "message": {
                "text": text,
                "from": {"id": 1234567890123, "first_name": "Ali", "language_code": "uz"},
                "chat": {"id": 1234567890123, "type": "private"},
            }
        }

    def issue_link(self):
        _, raw_token = TelegramLinkToken.issue(restaurant=self.branch, issued_by=None)
        return raw_token

    def test_start_payload_consumes_single_use_link_token(self):
        raw_token = self.issue_link()
        self.handler.handle(self.message(f"/start {raw_token}"))

        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertTrue(
            TelegramBranchSubscription.objects.filter(account=account, restaurant=self.branch).exists()
        )
        sent = FakeTelegramClient.sent_messages[-1]
        self.assertIn("Qamish", sent["text"])
        self.assertEqual(sent["reply_markup"], MAIN_KEYBOARD)
        self.assertEqual(MAIN_KEYBOARD["keyboard"], [[{"text": BRANCHES_BUTTON_TEXT}]])
        token = TelegramLinkToken.objects.get()
        self.assertIsNotNone(token.consumed_at)
        self.assertEqual(token.consumed_by, account)

    def test_consumed_link_cannot_be_used_by_second_account(self):
        raw_token = self.issue_link()
        self.handler.handle(self.message(f"/start {raw_token}"))
        second_message = self.message(f"/start {raw_token}")
        second_message["message"]["from"]["id"] = 9876543210
        second_message["message"]["chat"]["id"] = 9876543210

        self.handler.handle(second_message)

        second_account = TelegramAccount.objects.get(telegram_user_id=9876543210)
        self.assertFalse(second_account.branch_subscriptions.exists())
        sent = FakeTelegramClient.sent_messages[-1]
        self.assertIn("yaroqsiz", sent["text"])

    def test_legacy_restaurant_code_no_longer_links_account(self):
        self.handler.handle(self.message("/start A1b2C3"))

        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertFalse(account.branch_subscriptions.exists())
        self.assertIn("yaroqsiz", FakeTelegramClient.sent_messages[-1]["text"])

    def test_week_and_month_commands_send_current_reports_for_each_branch(self):
        second_branch = Restaurant.objects.create(name="Chilonzor")
        account = self.handler.get_account(
            sender={"id": 1234567890123, "first_name": "Ali", "language_code": "uz"},
            chat={"id": 1234567890123, "type": "private"},
        )
        TelegramBranchSubscription.objects.bulk_create(
            [
                TelegramBranchSubscription(account=account, restaurant=self.branch),
                TelegramBranchSubscription(account=account, restaurant=second_branch),
            ]
        )
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

    def test_connect_only_explains_secure_link_flow(self):
        self.handler.handle(self.message("/connect"))
        account = TelegramAccount.objects.get(telegram_user_id=1234567890123)
        self.assertEqual(account.state, TelegramAccount.State.IDLE)
        self.assertEqual(account.branch_subscriptions.count(), 0)
        self.assertIn("5 daqiqalik", FakeTelegramClient.sent_messages[-1]["text"])

    def test_disconnect_callback_only_removes_subscription(self):
        account = self.handler.get_account(
            sender={"id": 1234567890123, "first_name": "Ali", "language_code": "uz"},
            chat={"id": 1234567890123, "type": "private"},
        )
        subscription = TelegramBranchSubscription.objects.create(account=account, restaurant=self.branch)

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
