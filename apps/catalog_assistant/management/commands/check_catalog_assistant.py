import io
import json
import secrets
import time
from urllib.parse import urlparse
import httpx
from PIL import Image, ImageDraw
from openpyxl import Workbook
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from apps.catalog_assistant.ai import extract_menu
from apps.catalog_assistant.inputs import normalize_input
from apps.catalog_assistant.models import ManagementBotUpdate
from apps.catalog_assistant.bot_client import ManagementBotClient


class Command(BaseCommand):
    help = 'Verify management bot wiring and optionally extract a synthetic menu; never writes catalog data.'

    def add_arguments(self, parser):
        parser.add_argument('--live-ai', action='store_true')
        parser.add_argument('--webhook-url')

    def handle(self, *args, **options):
        identity = ManagementBotClient().call('getMe')
        self.stdout.write(json.dumps({'bot': identity['username'], 'inline': identity.get('supports_inline_queries', False)}))
        if options['live_ai']:
            book = Workbook()
            book.active.append(['Manti', 8000])
            workbook = io.BytesIO()
            book.save(workbook)
            picture = Image.new('RGB', (600, 150), 'white')
            ImageDraw.Draw(picture).text((30, 40), 'Choy 6000', fill='black', font_size=40)
            photo = io.BytesIO()
            picture.save(photo, 'PNG')
            content = normalize_input('Osh 35000', [
                SimpleUploadedFile('menu.xlsx', workbook.getvalue()),
                SimpleUploadedFile('menu.png', photo.getvalue(), 'image/png'),
            ])
            started = time.monotonic()
            rows = extract_menu(content, ['Taomlar', 'Ichimliklar'])
            prices = {row['name'].strip().casefold(): row['price'] for row in rows}
            expected = {'osh': 35000, 'manti': 8000, 'choy': 6000}
            if prices != expected:
                raise CommandError('Synthetic menu extraction did not match all three source prices.')
            if any(row['sale_unit'] != 'piece' or row['warning'] for row in rows):
                raise CommandError('Clear prices without currency/unit labels should use UZS and piece without warnings.')
            self.stdout.write(json.dumps({'liveAI': 'passed', 'rows': len(rows), 'seconds': round(time.monotonic() - started, 2)}))
        if options['webhook_url']:
            url = options['webhook_url']
            if urlparse(url).scheme != 'https' or not settings.MANAGEMENT_BOT_WEBHOOK_SECRET:
                raise CommandError('HTTPS webhook URL and configured secret required.')
            # A non-private update is deliberately ignored by the handler. This
            # proves the public endpoint, broker and worker without contacting users.
            update_id = -secrets.randbelow(2**50) - 1
            payload = {'update_id': update_id, 'message': {'chat': {'id': 0, 'type': 'group'}}}
            try:
                response = httpx.post(url, json=payload, timeout=20,
                    headers={'X-Telegram-Bot-Api-Secret-Token': settings.MANAGEMENT_BOT_WEBHOOK_SECRET})
                response.raise_for_status()
            except httpx.HTTPError:
                raise CommandError('Public webhook delivery failed.') from None
            for _ in range(30):
                update = ManagementBotUpdate.objects.filter(update_id=update_id).first()
                if update and update.status == 'done':
                    self.stdout.write('Public webhook and queue worker: passed')
                    return
                time.sleep(1)
            raise CommandError('Webhook queued update was not processed within 30 seconds.')
