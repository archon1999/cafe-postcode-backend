import json

from django.core.management.base import BaseCommand, CommandError

from apps.platform.services.ai_history_estimation import estimate_recovered_catalog_usage
from apps.platform.services.ai_history_recovery import RecoveryEvidenceError


class Command(BaseCommand):
    help = 'Estimate recovered menu tokens using the operator-confirmed model. Read-only unless --apply.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--apply', action='store_true')
        mode.add_argument('--dry-run', action='store_true')
        parser.add_argument('--model', required=True, choices=['gpt-5.6-luna'])
        parser.add_argument('--expected-count', type=int)

    def handle(self, *args, **options):
        expected = options['expected_count']
        if expected is not None and expected < 0:
            raise CommandError('Expected count cannot be negative.')
        try:
            result = estimate_recovered_catalog_usage(model=options['model'], apply=options['apply'], expected_count=expected)
        except RecoveryEvidenceError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result))
