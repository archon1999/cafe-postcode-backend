from django.core.management.base import BaseCommand
from django.db import transaction

from apps.integrations.models import IntegrationConfig


class Command(BaseCommand):
    help = 'Re-encrypt every integration settings envelope with the primary INTEGRATION_FERNET_KEYS key.'

    def handle(self, *args, **options):
        rotated = 0
        with transaction.atomic():
            for config in IntegrationConfig.objects.all().iterator(chunk_size=200):
                config.save(update_fields=['settings'])
                rotated += 1
        self.stdout.write(self.style.SUCCESS(f'Rotated {rotated} integration settings envelope(s).'))
