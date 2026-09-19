from urllib.parse import urlparse
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.catalog_assistant.bot_client import ManagementBotClient


class Command(BaseCommand):
    help = 'Configure the management bot and optionally bind its HTTPS webhook.'

    def add_arguments(self, parser):
        parser.add_argument('--webhook-url')

    def handle(self, *args, **options):
        client = ManagementBotClient()
        identity = client.call('getMe')
        if identity['username'].lower() != settings.MANAGEMENT_BOT_USERNAME.lower():
            raise CommandError('Bot username does not match MANAGEMENT_BOT_USERNAME.')
        client.call('setMyName', {'name': 'Postcode | Menyu va zallar'})
        client.call('setMyDescription', {'description': 'Postcode restoran boshqaruvi: menyu, narxlar, stop-list, AI import va zallar. Admin paneldagi shaxsiy havola orqali ulaning.'})
        client.call('setMyShortDescription', {'short_description': 'Menyu va zallarni Telegram orqali boshqaring.'})
        client.call('setMyCommands', {'commands': [
            {'command': 'menu', 'description': 'Menyu va zallarni boshqarish'},
            {'command': 'cancel', 'description': 'Joriy amalni bekor qilish'},
            {'command': 'disconnect', 'description': 'Telegram ulanishini uzish'},
        ]})
        if options['webhook_url']:
            url = options['webhook_url']
            if urlparse(url).scheme != 'https' or not settings.MANAGEMENT_BOT_WEBHOOK_SECRET:
                raise CommandError('HTTPS URL and MANAGEMENT_BOT_WEBHOOK_SECRET are required.')
            client.call('setWebhook', {'url': url, 'secret_token': settings.MANAGEMENT_BOT_WEBHOOK_SECRET,
                                     'allowed_updates': ['message', 'callback_query', 'inline_query'], 'drop_pending_updates': False})
        info = client.call('getWebhookInfo')
        self.stdout.write(f'Bot: @{identity["username"]}; inline: {identity.get("supports_inline_queries", False)}; webhook: {info.get("url", "")}; pending: {info.get("pending_update_count", 0)}')
        if not identity.get('supports_inline_queries'):
            self.stdout.write('Enable inline mode using @BotFather /setinline for this bot.')
