import io
from pathlib import PurePosixPath
import httpx
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError
from apps.telegram_reports.client import TelegramBotClient, TelegramAPIError
from .inputs import MAX_FILE_BYTES


class ManagementBotClient(TelegramBotClient):
    def __init__(self):
        super().__init__(getattr(settings, 'MANAGEMENT_BOT_TOKEN', ''))

    def call(self, method, payload=None):
        try:
            return super().call(method, payload)
        except TelegramAPIError as error:
            if method == 'editMessageText' and error.error_code == 400 and 'message is not modified' in str(error).lower():
                return {'message_id': payload['message_id']}
            # Transport exception URLs contain the bot token. Never chain them.
            raise TelegramAPIError('Telegram bilan bog‘lanib bo‘lmadi.',
                                   error_code=error.error_code, retry_after=error.retry_after) from None

    def download(self, file_id, name='photo.jpg'):
        info = self.call('getFile', {'file_id': file_id})
        path = str(info.get('file_path', ''))
        if info.get('file_size', 0) > MAX_FILE_BYTES or not path or '..' in PurePosixPath(path).parts:
            raise ValidationError('Faylni o‘qib bo‘lmadi yoki hajmi 10 MB dan katta.')
        # Telegram's file path is used only under the fixed Telegram origin.
        output = io.BytesIO()
        try:
            with httpx.Client(proxy=settings.TELEGRAM_PROXY_URL or None, timeout=30) as client:
                with client.stream('GET', f'https://api.telegram.org/file/bot{self.token}/{path}') as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        if output.tell() > MAX_FILE_BYTES:
                            raise ValidationError('Fayl 10 MB dan katta.')
        except httpx.HTTPError:
            raise TelegramAPIError('Telegram faylini yuklab bo‘lmadi.') from None
        return SimpleUploadedFile(name, output.getvalue())
