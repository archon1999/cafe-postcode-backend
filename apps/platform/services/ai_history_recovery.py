"""Recover only provider usage proven by durable application evidence.

CatalogDraft is created only after a validated AI response. It does not retain
provider token counts or the actual model; those values must stay unknown.
HTTP requests alone are not imported: validation and cache hits are not paid calls.
"""
from contextlib import nullcontext
from uuid import NAMESPACE_URL, uuid5

from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Min
from django.utils import timezone

from apps.catalog_assistant.models import CatalogDraft
from apps.platform.models import AIUsageLog


class RecoveryEvidenceError(ValueError):
    pass


def historical_cutoff():
    migration = MigrationRecorder.Migration.objects.filter(app='platform', name='0014_ai_usage_log').first()
    if migration is None:
        raise RecoveryEvidenceError('The original AI usage migration timestamp is required.')
    first_live = AIUsageLog.objects.filter(source=AIUsageLog.Source.LIVE).aggregate(first=Min('created_at'))['first']
    return min(migration.applied, first_live) if first_live else migration.applied


def _draft_values(draft, recovered_at):
    restaurant, user = draft.restaurant, draft.owner
    partner = restaurant.business_partner
    key = f'catalog_draft:{draft.pk}'
    return {
        'id': uuid5(NAMESPACE_URL, 'cafe-postcode:ai-history:' + key),
        'restaurant': restaurant, 'business_partner': partner, 'user': user,
        'restaurant_name': restaurant.name[:255],
        'business_partner_name': str(getattr(partner, 'company_name', '') or '')[:255],
        'user_name': str(user.full_name or user.username or '')[:255],
        'feature': AIUsageLog.Feature.CATALOG_MENU, 'provider': 'openai',
        'model': 'unknown', 'status': AIUsageLog.Status.SUCCESS,
        'input_tokens': None, 'cached_input_tokens': None, 'output_tokens': None,
        'total_tokens': None, 'estimated_cost_usd': None, 'pricing': {},
        'duration_ms': None, 'request_id': '', 'provider_status': '',
        'source': AIUsageLog.Source.CATALOG_DRAFT, 'recovery_key': key,
        'recovered_at': recovered_at,
        'evidence': {'kind': 'catalog_draft', 'sourceId': str(draft.pk),
                     'occurredAtBasis': 'draft_created_at'},
    }


def recover_catalog_usage(*, apply=False, expected_count=None):
    with transaction.atomic() if apply else nullcontext():
        if apply and connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [713200014])
        cutoff = historical_cutoff()
        drafts = list(CatalogDraft.objects.filter(created_at__lt=cutoff)
                      .select_related('restaurant__business_partner', 'owner').order_by('created_at', 'id'))
        eligible = [draft for draft in drafts if isinstance(draft.rows, list) and 1 <= len(draft.rows) <= 100]
        if expected_count is not None and len(eligible) != expected_count:
            raise RecoveryEvidenceError(f'Expected {expected_count} proven drafts; found {len(eligible)}. No records were imported.')
        keys = {f'catalog_draft:{draft.pk}' for draft in eligible}
        existing = {row.recovery_key: row for row in AIUsageLog.objects.filter(recovery_key__in=keys)}
        for draft in eligible:
            key = f'catalog_draft:{draft.pk}'
            row = existing.get(key)
            if row is not None and (
                row.source != AIUsageLog.Source.CATALOG_DRAFT
                or row.feature != AIUsageLog.Feature.CATALOG_MENU
                or row.restaurant_id != draft.restaurant_id
                or row.created_at != draft.created_at
            ):
                raise RecoveryEvidenceError('A recovery key conflicts with existing evidence. No records were imported.')
        missing = [draft for draft in eligible if f'catalog_draft:{draft.pk}' not in existing]
        imported_at = timezone.now()
        if apply:
            for draft in missing:
                row = AIUsageLog.objects.create(**_draft_values(draft, imported_at))
                # BaseModel auto_now_add records insert time. The report time is
                # the original evidence timestamp, while recovered_at retains import time.
                AIUsageLog.objects.filter(pk=row.pk).update(created_at=draft.created_at)
        return {
            'mode': 'apply' if apply else 'dry_run', 'cutoff': cutoff.isoformat(),
            'eligible': len(eligible), 'alreadyRecovered': len(existing),
            'skippedUnprovenDrafts': len(drafts) - len(eligible),
            'willCreate': len(missing), 'created': len(missing) if apply else 0,
            'firstEvidenceAt': eligible[0].created_at.isoformat() if eligible else None,
            'lastEvidenceAt': eligible[-1].created_at.isoformat() if eligible else None,
            'branchCount': len({draft.restaurant_id for draft in eligible}),
            'tokenCountsRecovered': 0, 'costsRecovered': 0,
        }
