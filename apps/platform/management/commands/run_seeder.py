from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .seeder import bootstrap_demo


class Command(BaseCommand):
    help = 'Restaurant va fast food demo maʼlumotlarini yaratadi.'

    def handle(self, *args, **options):
        if settings.DJANGO_PRODUCTION:
            raise CommandError('run_seeder is disabled when DJANGO_PRODUCTION=1.')
        bootstrap_demo(self)
