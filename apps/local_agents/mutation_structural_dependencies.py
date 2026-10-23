"""Legacy envelopes retain their hashes; missing object prerequisites are derived."""
import re
import uuid

from apps.floor.models import TableSession
from apps.sales.models import Order
from apps.local_agents.models import LocalAgentMutationInbox
from apps.local_agents.mutation_results import mutation_error_result


def structural_dependency_result(*, agent, operation_id, path, body):
    references = []
    if path == '/api/v1/pos/sales/orders/':
        references.append(('tableSession', body.get('tableSession') or body.get('table_session'),
                           TableSession, '/api/v1/pos/floor/table-sessions/'))
    match = re.fullmatch(r'/api/v1/pos/(?:sales|billing)/orders/([0-9a-f-]+)/(?:items/|items/bulk/|submit/|serve-ready/|scan-marking/|pay/)?', path)
    if match:
        references.append(('order', match[1], Order, '/api/v1/pos/sales/orders/'))
    match = re.fullmatch(r'/api/v1/pos/floor/table-sessions/([0-9a-f-]+)/(?:move|merge|transfer|group|ungroup)/', path)
    if match:
        references.append(('tableSession', match[1], TableSession, '/api/v1/pos/floor/table-sessions/'))
        target = body.get('targetSessionId') or body.get('target_session_id')
        if target:
            references.append(('tableSession', target, TableSession, '/api/v1/pos/floor/table-sessions/'))
    missing, blockers = [], []
    for kind, raw_id, model, creator_path in references:
        if not raw_id:
            continue
        try:
            identity = uuid.UUID(str(raw_id))
        except (ValueError, TypeError, AttributeError):
            continue  # The normal serializer reports invalid input.
        if model.objects.filter(pk=identity).exists():
            continue  # Normal tenant validation still applies.
        creators = LocalAgentMutationInbox.objects.filter(
            restaurant=agent.restaurant, operation__path=creator_path,
            operation__body__id=str(identity),
        ).exclude(operation_id=operation_id)
        # A completed deletion is a real 404, not an indefinitely missing dependency.
        if creators.filter(state__in=['applied', 'resolved']).exists():
            continue
        missing.append({'type': kind, 'id': str(identity)})
        blockers.extend(creators.values_list('operation_id', flat=True))
    if not missing:
        return None
    result = mutation_error_result(
        operation_id=operation_id, response_status=409,
        error='The original session or order must be applied first.',
        retryable=True, code='DEPENDENCY_WAIT',
        resolution_hint='Waiting for the original prerequisite; inspect its root failure.',
    )
    result.update(missingResources=missing, blockedBy=sorted(set(blockers)))
    return result
