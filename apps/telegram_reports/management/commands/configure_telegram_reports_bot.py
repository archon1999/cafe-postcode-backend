from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.telegram_reports.bot_profile import (
    BOT_COMMANDS,
    BOT_DESCRIPTION,
    BOT_NAME,
    BOT_SHORT_DESCRIPTION,
)
from apps.telegram_reports.client import TelegramAPIError, TelegramBotClient


class Command(BaseCommand):
    help = "Configure the Telegram reports bot profile, commands, menu and optional webhook."

    def add_arguments(self, parser):
        parser.add_argument("--set-webhook", action="store_true")
        parser.add_argument("--drop-pending-updates", action="store_true")

    def handle(self, *args, **options):
        try:
            client = TelegramBotClient()
            client.call("setMyName", {"name": BOT_NAME})
            client.call("setMyDescription", {"description": BOT_DESCRIPTION})
            client.call("setMyShortDescription", {"short_description": BOT_SHORT_DESCRIPTION})
            client.call("setMyCommands", {"commands": BOT_COMMANDS})
            client.call("setChatMenuButton", {"menu_button": {"type": "commands"}})
            if options["set_webhook"]:
                if not settings.TELEGRAM_REPORTS_WEBHOOK_URL:
                    raise CommandError("TELEGRAM_REPORTS_WEBHOOK_URL is required with --set-webhook.")
                payload = {
                    "url": settings.TELEGRAM_REPORTS_WEBHOOK_URL,
                    "allowed_updates": ["message", "callback_query"],
                    "drop_pending_updates": options["drop_pending_updates"],
                }
                if settings.TELEGRAM_REPORTS_WEBHOOK_SECRET:
                    payload["secret_token"] = settings.TELEGRAM_REPORTS_WEBHOOK_SECRET
                client.call("setWebhook", payload)
        except TelegramAPIError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Telegram reports bot profile configured."))

