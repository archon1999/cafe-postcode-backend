from __future__ import annotations

import httpx
from django.conf import settings


class TelegramAPIError(Exception):
    def __init__(self, message: str, *, error_code: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after


class TelegramBotClient:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else settings.TELEGRAM_REPORTS_BOT_TOKEN
        if not self.token:
            raise TelegramAPIError("Telegram reports bot token is not configured.")
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def call(self, method: str, payload: dict | None = None) -> dict:
        try:
            with httpx.Client(
                proxy=settings.TELEGRAM_PROXY_URL or None,
                timeout=settings.TELEGRAM_TIMEOUT,
            ) as client:
                response = client.post(f"{self.base_url}/{method}", json=payload or {})
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TelegramAPIError("Telegram bilan bog‘lanib bo‘lmadi.") from error

        if response.is_error or data.get("ok") is not True:
            parameters = data.get("parameters") or {}
            raise TelegramAPIError(
                str(data.get("description") or "Telegram so‘rovni rad etdi."),
                error_code=data.get("error_code") or response.status_code,
                retry_after=parameters.get("retry_after"),
            )
        return data.get("result")

    def send_message(self, *, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, *, text: str = "") -> dict:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self.call("answerCallbackQuery", payload)

