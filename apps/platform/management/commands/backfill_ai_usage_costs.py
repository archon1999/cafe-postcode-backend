from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.platform.models import AIUsageLog
from apps.platform.services.ai_pricing import estimated_cost


class Command(BaseCommand):
    help = 'Estimate only unpriced OpenAI usage with complete recorded tokens. Dry run unless --apply.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--apply', action='store_true', help='Persist estimates and their current rate snapshots.')
        mode.add_argument('--dry-run', action='store_true', help='Report eligible records without writing (the default).')

    def handle(self, *args, **options):
        eligible = skipped = applied = 0
        estimated_total = Decimal('0')
        applied_total = Decimal('0')
        rows = AIUsageLog.objects.filter(provider='openai', estimated_cost_usd__isnull=True).only(
            'id', 'model', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens',
        ).order_by('id')
        for row in rows.iterator(chunk_size=500):
            usage = {field: getattr(row, field) for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')}
            cost, pricing = estimated_cost(row.model, usage)
            if cost is None:
                skipped += 1
                continue
            eligible += 1
            estimated_total += cost
            if options['apply']:
                # The NULL condition also protects already-priced history if
                # another worker prices the same row after our read.
                changed = AIUsageLog.objects.filter(pk=row.pk, estimated_cost_usd__isnull=True).update(
                    estimated_cost_usd=cost, pricing=pricing, updated_at=timezone.now(),
                )
                applied += changed
                if changed:
                    applied_total += cost
        mode = 'APPLIED' if options['apply'] else 'DRY RUN'
        self.stdout.write(f'{mode}: eligible={eligible}, skipped={skipped}, applied={applied}, estimated_usd={estimated_total:.12f}, applied_usd={applied_total:.12f}')
        if not options['apply']:
            self.stdout.write('No records changed. Use --apply to persist these estimates; existing prices are never overwritten.')
