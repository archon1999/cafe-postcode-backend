"""Explicitly approximate recovered menu usage without changing provider observations.

The owner confirmed the historical model. The original requests/responses are
not retained: saved (possibly reviewed) menu rows are proxies, never exact usage.
No provider calls or source content are written to the accounting log.
"""
import json
from contextlib import nullcontext
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

from apps.catalog_assistant.ai import PROPERTIES, SCHEMA, menu_instructions
from apps.catalog_assistant.models import CatalogDraft
from apps.platform.models import AIUsageLog
from apps.platform.services.ai_history_recovery import RecoveryEvidenceError, historical_cutoff
from apps.platform.services.ai_pricing import estimated_cost

CONFIRMED_MODEL = 'gpt-5.6-luna'
ESTIMATION_METHOD = 'catalog_draft_text_v1'
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')
UNAVAILABLE_COMPONENTS = [
    'original_uploads', 'original_category_context', 'reasoning_tokens', 'cache_usage', 'review_edits',
]


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _text_tokens(text):
    # A deliberately coarse multilingual proxy: ~4 UTF-8 bytes/token. English
    # averages ~4 chars/token; Cyrillic receives more weight through UTF-8 bytes.
    # This is not an exact tokenizer and does not claim a bound on billed usage.
    return max(1, (len(text.encode('utf-8')) + 3) // 4)


def estimate_draft_tokens(draft):
    if not isinstance(draft.rows, list) or not 1 <= len(draft.rows) <= 100:
        raise RecoveryEvidenceError('The saved menu cannot support a token estimate.')
    rows = []
    for row in draft.rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'].strip():
            raise RecoveryEvidenceError('The saved menu cannot support a token estimate.')
        # Exclude review/UI-only columns, category UUIDs, MXIK additions, etc.
        rows.append({key: row.get(key, None if key == 'price' else 'piece' if key == 'sale_unit' else '')
                     for key in PROPERTIES})
    categories = sorted({row['category_name'] for row in rows if isinstance(row['category_name'], str) and row['category_name']})
    source_proxy = '\n'.join(dict.fromkeys(
        str(row['evidence'] or f"{row['name']} {row['price'] if row['price'] is not None else ''}") for row in rows
    ))
    # The current prompt/schema and saved category names approximate missing
    # historical context. Source excerpts may be edited or only part of a file.
    incoming_text = menu_instructions(categories) + '\n' + _json(SCHEMA) + '\n' + source_proxy
    outgoing_text = _json({'rows': rows})
    incoming = _text_tokens(incoming_text) + 16  # approximate message/framing overhead
    outgoing = _text_tokens(outgoing_text)
    usage = {'input_tokens': incoming, 'cached_input_tokens': 0,
             'output_tokens': outgoing, 'total_tokens': incoming + outgoing}
    cost, pricing = estimated_cost(CONFIRMED_MODEL, usage)
    if cost is None:
        raise RecoveryEvidenceError('The confirmed model requires a valid price snapshot before estimation.')
    return usage, cost, {**pricing, 'usage_basis': ESTIMATION_METHOD, 'cached_input_assumption': 0}, {
        'rowCount': len(rows), 'inputProxyBytes': len(incoming_text.encode('utf-8')),
        'outputProxyBytes': len(outgoing_text.encode('utf-8')),
    }


def estimate_recovered_catalog_usage(*, model, apply=False, expected_count=None):
    if model != CONFIRMED_MODEL:
        raise RecoveryEvidenceError('Historical model confirmation must be gpt-5.6-luna.')
    if apply and expected_count is None:
        raise RecoveryEvidenceError('Apply requires a reviewed expected count.')
    with transaction.atomic() if apply else nullcontext():
        if apply and connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [713200014])
        logs = list(AIUsageLog.objects.filter(source=AIUsageLog.Source.CATALOG_DRAFT).order_by('created_at', 'id'))
        if expected_count is not None and len(logs) != expected_count:
            raise RecoveryEvidenceError(f'Expected {expected_count} recovered records; found {len(logs)}. Nothing changed.')
        drafts = {f'catalog_draft:{draft.pk}': draft for draft in CatalogDraft.objects.filter(
            created_at__lt=historical_cutoff())}
        pending, already = [], 0
        estimated_at = timezone.now().isoformat()
        for row in logs:
            draft = drafts.get(row.recovery_key)
            if (draft is None or row.feature != AIUsageLog.Feature.CATALOG_MENU
                    or row.status != AIUsageLog.Status.SUCCESS or row.model not in ('unknown', model)
                    or row.restaurant_id != draft.restaurant_id or row.created_at != draft.created_at
                    or row.evidence.get('sourceId') != str(draft.pk)):
                raise RecoveryEvidenceError('Recovered usage does not match its original evidence. Nothing changed.')
            if row.usage_is_estimated:
                if (row.model != model or row.evidence.get('usageEstimate', {}).get('method') != ESTIMATION_METHOD
                        or row.total_tokens is None or row.estimated_cost_usd is None):
                    raise RecoveryEvidenceError('Existing estimate conflicts with this method. Nothing changed.')
                already += 1
                continue  # Freeze the original estimate even if the draft is edited later.
            if any(getattr(row, key) is not None for key in (*TOKEN_FIELDS, 'estimated_cost_usd')):
                raise RecoveryEvidenceError('Existing usage measurements must not be overwritten. Nothing changed.')
            usage, cost, pricing, sizes = estimate_draft_tokens(draft)
            evidence = {**row.evidence, 'usageEstimate': {
                'method': ESTIMATION_METHOD, 'estimatedAt': estimated_at,
                'modelBasis': 'operator_confirmed', 'basis': 'saved_catalog_draft',
                'cachedInputAssumed': 0, 'unavailableComponents': UNAVAILABLE_COMPONENTS, **sizes,
            }}
            pending.append((row, {
                'model': model, 'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
                'total_tokens': usage['total_tokens'], 'estimated_cost_usd': cost, 'pricing': pricing,
                # Unknown cache/reasoning/duration remain unknown. Pricing assumes no cache discount.
                'usage_is_estimated': True, 'evidence': evidence,
            }))
        if apply:
            for row, values in pending:
                AIUsageLog.objects.filter(pk=row.pk, usage_is_estimated=False).update(**values)
        previous_tokens = sum(row.total_tokens or 0 for row in logs if row.usage_is_estimated)
        previous_cost = sum((row.estimated_cost_usd or Decimal(0) for row in logs if row.usage_is_estimated), Decimal(0))
        return {
            'mode': 'apply' if apply else 'dry_run', 'model': model, 'method': ESTIMATION_METHOD,
            'eligible': len(logs), 'alreadyEstimated': already, 'willEstimate': len(pending),
            'updated': len(pending) if apply else 0,
            'estimatedTotalTokens': previous_tokens + sum(values['total_tokens'] for _, values in pending),
            'estimatedTotalCostUsd': str(previous_cost + sum((values['estimated_cost_usd'] for _, values in pending), Decimal(0))),
            'branchCount': len({row.restaurant_id for row in logs}),
        }
