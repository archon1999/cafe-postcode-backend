from __future__ import annotations

import html
import re
from uuid import UUID

from django.utils import timezone

from apps.reporting.services import CommonReportService
from apps.restaurants.models import Restaurant
from apps.telegram_reports.client import TelegramBotClient
from apps.telegram_reports.models import TelegramAccount, TelegramBranchSubscription, TelegramReportDelivery
from apps.telegram_reports.services import TelegramBranchStatusService, TelegramReportService


BRANCHES_BUTTON_TEXT = "🏪 Mening shahobchalarim"
MAIN_KEYBOARD = {
    "keyboard": [[{"text": BRANCHES_BUTTON_TEXT}]],
    "resize_keyboard": True,
    "is_persistent": True,
}
CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{6}$")


class TelegramUpdateHandler:
    client_class = TelegramBotClient
    report_service_class = TelegramReportService
    status_service_class = TelegramBranchStatusService
    common_report_service_class = CommonReportService

    def handle(self, update: dict) -> None:
        if callback := update.get("callback_query"):
            self.handle_callback(callback)
            return
        if message := update.get("message"):
            self.handle_message(message)

    def handle_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if chat.get("type") != "private" or not sender.get("id"):
            return
        account = self.get_account(sender=sender, chat=chat)
        text = str(message.get("text") or "").strip()
        command, argument = self.parse_command(text)

        if command == "start":
            account.state = TelegramAccount.State.IDLE
            account.save(update_fields=("state", "updated_at"))
            self.send(
                account,
                "👋 <b>PosCode Hisobot botiga xush kelibsiz!</b>\n\n"
                "Shahobcha kodini ulash uchun /connect komandasini yuboring. "
                "Bir nechta kodni vergul yoki yangi qator bilan yuborishingiz mumkin.",
            )
        elif command == "connect":
            if argument:
                self.connect_codes(account, argument)
            else:
                account.state = TelegramAccount.State.AWAITING_CONNECT
                account.save(update_fields=("state", "updated_at"))
                self.send(
                    account,
                    "🔗 Shahobcha kodini yuboring.\n\nMasalan: <code>A1b2C3, X9y8Z7</code>",
                )
        elif command == "disconnect":
            self.show_disconnect_menu(account)
        elif command == "notifications_on":
            account.notifications_enabled = True
            account.save(update_fields=("notifications_enabled", "updated_at"))
            self.send(account, "🔔 Avtomatik kunlik, haftalik va oylik hisobotlar yoqildi.")
        elif command == "notifications_off":
            account.notifications_enabled = False
            account.save(update_fields=("notifications_enabled", "updated_at"))
            self.send(account, "🔕 Avtomatik hisobotlar o‘chirildi. /today orqali qo‘lda olishingiz mumkin.")
        elif command == "today":
            self.send_today_reports(account)
        elif command == "settings":
            self.send_settings(account)
        elif command == "help":
            self.send_help(account)
        elif text == BRANCHES_BUTTON_TEXT:
            self.send_branches(account)
        elif account.state == TelegramAccount.State.AWAITING_CONNECT or self.looks_like_codes(text):
            self.connect_codes(account, text)
        else:
            self.send(account, "Komanda tushunilmadi. /help orqali komandalarni ko‘ring.")

    def handle_callback(self, callback: dict) -> None:
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        callback_id = str(callback.get("id") or "")
        if chat.get("type") != "private" or not sender.get("id"):
            if callback_id:
                self.client_class().answer_callback_query(callback_id)
            return
        account = self.get_account(sender=sender, chat=chat)
        data = str(callback.get("data") or "")
        if data.startswith("disconnect:"):
            subscription_id = data.partition(":")[2]
            try:
                subscription_id = str(UUID(subscription_id))
            except ValueError:
                self.client_class().answer_callback_query(callback_id, text="Noto‘g‘ri so‘rov")
                return
            subscription = TelegramBranchSubscription.objects.filter(
                id=subscription_id,
                account=account,
            ).select_related("restaurant").first()
            if subscription:
                branch_name = subscription.restaurant.name
                subscription.delete()
                self.client_class().answer_callback_query(callback_id, text="Shahobcha uzildi")
                self.send(account, f"✅ <b>{html.escape(branch_name)}</b> shahobchasi uzildi.")
            else:
                self.client_class().answer_callback_query(callback_id, text="Shahobcha topilmadi")
            return
        self.client_class().answer_callback_query(callback_id)

    @staticmethod
    def parse_command(text: str) -> tuple[str | None, str]:
        if not text.startswith("/"):
            return None, ""
        head, _, argument = text.partition(" ")
        command = head[1:].partition("@")[0].lower()
        return command, argument.strip()

    @staticmethod
    def parse_codes(text: str) -> list[str]:
        candidates = re.split(r"[,;\s]+", text.strip())
        return list(dict.fromkeys(value for value in candidates if value))[:20]

    def looks_like_codes(self, text: str) -> bool:
        codes = self.parse_codes(text)
        return bool(codes) and all(CODE_PATTERN.fullmatch(code) for code in codes)

    def connect_codes(self, account: TelegramAccount, raw_codes: str) -> None:
        codes = self.parse_codes(raw_codes)
        account.state = TelegramAccount.State.IDLE
        account.save(update_fields=("state", "updated_at"))
        if not codes:
            self.send(account, "Kod topilmadi. Masalan: <code>A1b2C3, X9y8Z7</code>")
            return

        restaurants = {
            restaurant.auth_code: restaurant
            for restaurant in Restaurant.objects.filter(auth_code__in=codes)
        }
        lines = []
        for code in codes:
            if not CODE_PATTERN.fullmatch(code):
                lines.append(f"❌ <code>{html.escape(code)}</code> — kod 6 ta harf yoki raqamdan iborat bo‘lishi kerak")
                continue
            restaurant = restaurants.get(code)
            if restaurant is None:
                lines.append(f"❌ <code>{html.escape(code)}</code> — kod topilmadi")
                continue
            _, created = TelegramBranchSubscription.objects.get_or_create(
                account=account,
                restaurant=restaurant,
            )
            status_text = "ulandi" if created else "avval ulangan"
            lines.append(f"✅ <b>{html.escape(restaurant.name)}</b> — {status_text}")
        self.send(account, "\n".join(lines))

    def send_branches(self, account: TelegramAccount) -> None:
        subscriptions = account.branch_subscriptions.select_related("restaurant").all()
        if not subscriptions:
            self.send(account, "Hozircha shahobcha ulanmagan. Ulanish uchun /connect ni yuboring.")
            return
        report_service = self.report_service_class()
        common_service = self.common_report_service_class()
        today_period = report_service.build_today_period()
        for subscription in subscriptions:
            summary = common_service.build_summary(subscription.restaurant, today_period)
            text = self.status_service_class().render(
                restaurant=subscription.restaurant,
                today_summary=summary,
            )
            self.send(account, text)

    def send_today_reports(self, account: TelegramAccount) -> None:
        subscriptions = account.branch_subscriptions.select_related("restaurant").all()
        if not subscriptions:
            self.send(account, "Hisobot olish uchun avval /connect orqali shahobcha ulang.")
            return
        report_service = self.report_service_class()
        today_period = report_service.build_today_period()
        for subscription in subscriptions:
            text = report_service.render(
                restaurant=subscription.restaurant,
                report_type=TelegramReportDelivery.ReportType.DAILY,
                period=today_period,
            )
            self.send(account, text)

    def show_disconnect_menu(self, account: TelegramAccount) -> None:
        subscriptions = list(account.branch_subscriptions.select_related("restaurant").all())
        if not subscriptions:
            self.send(account, "Uzish uchun ulangan shahobcha yo‘q.")
            return
        keyboard = {
            "inline_keyboard": [
                [{"text": f"❌ {item.restaurant.name}", "callback_data": f"disconnect:{item.id}"}]
                for item in subscriptions
            ]
        }
        self.client_class().send_message(
            chat_id=account.chat_id,
            text="Uzmoqchi bo‘lgan shahobchani tanlang:",
            reply_markup=keyboard,
        )

    def send_settings(self, account: TelegramAccount) -> None:
        count = account.branch_subscriptions.count()
        notification_text = "yoqilgan 🔔" if account.notifications_enabled else "o‘chirilgan 🔕"
        self.send(
            account,
            f"⚙️ <b>Sozlamalar</b>\n\n"
            f"Ulangan shahobchalar: <b>{count} ta</b>\n"
            f"Avtomatik hisobotlar: <b>{notification_text}</b>\n\n"
            "Hisobot vaqtlari: 00:05 kunlik, dushanba 00:10 haftalik, oy boshida 00:15 oylik.",
        )

    def send_help(self, account: TelegramAccount) -> None:
        self.send(
            account,
            "ℹ️ <b>Komandalar</b>\n\n"
            "/connect — shahobcha ulash\n"
            "/disconnect — shahobchani uzish\n"
            "/notifications_on — avtomatik hisobotlarni yoqish\n"
            "/notifications_off — avtomatik hisobotlarni o‘chirish\n"
            "/today — bugungi hisobot\n"
            "/settings — sozlamalar",
        )

    def send(self, account: TelegramAccount, text: str) -> dict:
        return self.client_class().send_message(
            chat_id=account.chat_id,
            text=text,
            reply_markup=MAIN_KEYBOARD,
        )

    @staticmethod
    def get_account(*, sender: dict, chat: dict) -> TelegramAccount:
        now = timezone.now()
        account, _ = TelegramAccount.objects.update_or_create(
            telegram_user_id=sender["id"],
            defaults={
                "chat_id": chat["id"],
                "username": str(sender.get("username") or ""),
                "first_name": str(sender.get("first_name") or ""),
                "language_code": str(sender.get("language_code") or ""),
                "last_interaction_at": now,
            },
        )
        return account
