"""Operator entrypoint; a restaurant and explicit --apply are always required."""
import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.local_agents.evidence_retention import rehydrate_operation, run_retention
from apps.local_agents.models import AgentEvidencePayload, AgentEvidencePolicy
from apps.restaurants.models import Restaurant


class Command(BaseCommand):
    help = 'Dry-run, compact or archive successful Agent responses for one allowlisted restaurant.'

    def add_arguments(self, parser):
        parser.add_argument('--restaurant', required=True, type=UUID)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--archive', action='store_true')
        parser.add_argument('--batch-size', type=int, default=500)
        parser.add_argument('--max-seconds', type=int, default=120)
        parser.add_argument('--configure', choices=['pilot', 'pause', 'schedule'])
        parser.add_argument('--rehydrate', action='store_true')

    def handle(self, *args, **options):
        restaurant_id = options['restaurant']
        if not Restaurant.objects.filter(pk=restaurant_id).exists():
            raise CommandError('Restaurant does not exist.')
        configure = options['configure']
        if configure:
            if not options['apply']:
                raise CommandError('Changing the allowlist requires --apply.')
            if configure == 'pause':
                AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id).update(
                    writes_enabled=False, compaction_enabled=False, archive_enabled=False, schedule_enabled=False,
                )
            elif configure == 'pilot':
                AgentEvidencePolicy.objects.update_or_create(restaurant_id=restaurant_id, defaults={
                    'writes_enabled': True, 'compaction_enabled': True,
                    'archive_enabled': options['archive'], 'schedule_enabled': False,
                })
            else:
                from croniter import croniter
                from django_q.models import Schedule
                from django.utils import timezone
                if not AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id, compaction_enabled=True).exists():
                    raise CommandError('Configure and validate a pilot before scheduling maintenance.')
                Schedule.objects.update_or_create(name='local-agents.evidence-retention', defaults={
                    'func': 'apps.local_agents.evidence_retention.scheduled_retention',
                    'schedule_type': Schedule.CRON, 'cron': '45 2 * * *', 'repeats': -1,
                    'next_run': croniter('45 2 * * *', timezone.localtime()).get_next(type(timezone.localtime())),
                })
                AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id).update(schedule_enabled=True)
            self.stdout.write(json.dumps({'restaurant_id': str(restaurant_id), 'configuration': configure}))
            return
        if options['rehydrate']:
            policy = AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id).first()
            if not options['apply'] or policy is None or policy.writes_enabled or policy.compaction_enabled:
                raise CommandError('Pause this restaurant first; rehydration requires --apply.')
            ids = AgentEvidencePayload.objects.filter(restaurant_id=restaurant_id).order_by('operation_id').values_list('operation_id', flat=True).distinct()
            total = sum(rehydrate_operation(restaurant_id, operation_id) for operation_id in ids)
            self.stdout.write(json.dumps({'rehydrated_rows': total, 'restaurant_id': str(restaurant_id)}))
            return
        try:
            report = run_retention(restaurant_id=restaurant_id, apply=options['apply'], archive=options['archive'],
                                   batch_size=options['batch_size'], max_seconds=options['max_seconds'])
        except Exception as error:
            raise CommandError(f'Retention stopped safely: {type(error).__name__}. Inspect the policy report; hot data/guards are preserved.') from error
        self.stdout.write(json.dumps(report, sort_keys=True))
