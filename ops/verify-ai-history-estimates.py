"""Verify private before/after accounting snapshots; print only aggregate metadata."""
import json
import sys
from decimal import Decimal
from pathlib import Path

before = {row['pk']: row['fields'] for row in json.loads(Path(sys.argv[1]).read_text())}
after = {row['pk']: row['fields'] for row in json.loads(Path(sys.argv[2]).read_text())}
expected = int(sys.argv[3])
assert before.keys() <= after.keys(), 'Estimation must not delete requests'
concurrent = [after[pk] for pk in after.keys() - before.keys()]
assert all(row['source'] == 'live' and row['usage_is_estimated'] is False for row in concurrent), 'Unexpected new history rows'
allowed = {'model', 'input_tokens', 'output_tokens', 'total_tokens', 'estimated_cost_usd',
           'pricing', 'evidence', 'usage_is_estimated'}
live_count, recovered = 0, []
for pk, old in before.items():
    row = after[pk]
    if old['source'] != 'catalog_draft':
        assert row == old, 'Live provider observations changed'
        live_count += 1
        continue
    assert all(row[key] == value for key, value in old.items() if key not in allowed), 'Historical provenance changed'
    if old['usage_is_estimated']:
        assert row == old, 'Existing frozen estimate changed'
    else:
        assert all(old[key] is None for key in ('input_tokens', 'cached_input_tokens', 'output_tokens',
                                               'total_tokens', 'estimated_cost_usd')), 'Known usage was replaced'
    assert row['model'] == 'gpt-5.6-luna' and row['usage_is_estimated'] is True
    assert row['total_tokens'] == row['input_tokens'] + row['output_tokens'] > 0
    assert row['cached_input_tokens'] is None and row['duration_ms'] is None
    assert row['evidence']['usageEstimate']['method'] == 'catalog_draft_text_v1'
    assert row['evidence']['usageEstimate']['modelBasis'] == 'operator_confirmed'
    cost = (Decimal(row['input_tokens']) * Decimal(row['pricing']['input'])
            + Decimal(row['output_tokens']) * Decimal(row['pricing']['output'])) / 1000000
    assert Decimal(row['estimated_cost_usd']) == cost.quantize(Decimal('0.000000000001'))
    recovered.append(row)
assert len(recovered) == expected, 'Estimated history count differs from reviewed batch'
print(json.dumps({
    'verifiedEstimatedCount': str(len(recovered)), 'model': 'gpt-5.6-luna',
    'estimatedTotalTokens': str(sum(row['total_tokens'] for row in recovered)),
    'estimatedTotalInputTokens': str(sum(row['input_tokens'] for row in recovered)),
    'estimatedTotalOutputTokens': str(sum(row['output_tokens'] for row in recovered)),
    'estimatedTotalCostUsd': str(sum((Decimal(row['estimated_cost_usd']) for row in recovered), Decimal(0))),
    'liveRowsUnchanged': str(live_count), 'totalUsageRows': str(len(after)),
    'concurrentLiveRows': str(len(concurrent)),
    'privateBackup': sys.argv[1], 'duplicatesAdded': False,
}))
