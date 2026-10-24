import json

from django.core.management.base import BaseCommand, CommandError

from apps.platform.services.ai_history_recovery import RecoveryEvidenceError, recover_catalog_usage


class Command(BaseCommand):
    help = 'Recover proven, pre-tracking AI catalog usage. Defaults to a read-only dry run.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--apply', action='store_true')
        mode.add_argument('--dry-run', action='store_true')
        parser.add_argument('--expected-count', type=int, required=False)

    def handle(self, *args, **options):
        expected = options['expected_count']
        if expected is not None and expected < 0:
            raise CommandError('Expected count cannot be negative.')
        if options['apply'] and expected is None:
            raise CommandError('Apply requires --expected-count from the reviewed dry run.')
        try:
            result = recover_catalog_usage(apply=options['apply'], expected_count=expected)
        except RecoveryEvidenceError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result))
