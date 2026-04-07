from django.core.management.base import BaseCommand

from .seeder import bootstrap_demo


class Command(BaseCommand):
    help = 'Restaurant va fast food demo maʼlumotlarini yaratadi.'

    def handle(self, *args, **options):
        bootstrap_demo(self)
