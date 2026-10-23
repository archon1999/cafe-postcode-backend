"""Atomically project a complete historical sitting from immutable inbox evidence.

Unfinished histories remain pending. The live floor is never temporarily reopened
or cleared, and normal per-operation authorization and money validation still run.
"""
import copy
import re
import uuid

from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast, Length
from django.utils.dateparse import parse_datetime
from djangorestframework_camel_case.util import underscoreize
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.security import record_security_event
from apps.floor.models import DiningTable, TableSession
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.models import LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import _hash
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.sales.models import Order
from common.api.throttling import LocalAgentRateThrottle
from common.edge_replay import HistoricalFloorScope, historical_floor_projection


FLOOR_OPEN = '/api/v1/pos/floor/table-sessions/'
ORDER_OPEN = '/api/v1/pos/sales/orders/'
TRANSFER = re.compile(r'^/api/v1/pos/floor/table-sessions/([0-9a-f-]+)/transfer/$')
ORDER_ACTION = re.compile(r'^/api/v1/pos/(?:sales|billing)/orders/([0-9a-f-]+)/(?:items/|items/bulk/|submit/|serve-ready/|scan-marking/|pay/)?$')
ITEM_ACTION = re.compile(r'^/api/v1/pos/sales/orders/items/([0-9a-f-]+)/$')
SESSION_ACTION = re.compile(r'^/api/v1/pos/floor/table-sessions/([0-9a-f-]+)/(.*)$')


class HistoryPending(Exception):
    def __init__(self, code, detail, **data):
        self.result = {'ok': False, 'applied': False, 'code': code, 'detail': detail, **data}


def _body(inbox):
    body = inbox.operation.get('body') or {}
    if not isinstance(body, dict):
        return {}  # Unrelated malformed evidence must not block another sitting.
    return underscoreize(body)


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise HistoryPending('HISTORY_INVALID_IDENTITY', 'Original UUID identities are required.') from None


def _opening_time(row):
    try:
        opened = parse_datetime(str(_body(row).get('opened_at') or ''))
        valid = (opened is not None and opened.tzinfo is not None and row.occurred_at is not None
                 and abs((opened-row.occurred_at).total_seconds()) <= 60)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HistoryPending('HISTORY_OPEN_TIME_REQUIRED', 'The original session opening time is required.')
    return opened


def plan_historical_floor(*, agent, operation_id):
    root = LocalAgentMutationInbox.objects.filter(restaurant=agent.restaurant, operation_id=operation_id).first()
    if root is None or root.operation.get('method') != 'POST' or root.operation.get('path') != FLOOR_OPEN:
        raise HistoryPending('HISTORY_ROOT_REQUIRED', 'An original table opening is required.')
    if root.state == 'applied':
        return root, [], set(), set(), set()
    session_ids = {_uuid(_body(root).get('id'))}
    order_ids, item_ids, table_ids = set(), set(), set()
    # The bounded scan is read-only; only one connected sitting is ever locked.
    query = LocalAgentMutationInbox.objects.filter(
        restaurant=agent.restaurant,
    ).exclude(state__in=['applied', 'resolved']).order_by('occurred_at', 'created_at', 'pk')
    sizes = list(query.annotate(envelope_size=Length(Cast('operation', TextField()))).values_list('pk', 'envelope_size')[:10001])
    if len(sizes) > 10000 or sum(size or 0 for _, size in sizes) > 32 * 1024 * 1024:
        raise HistoryPending('HISTORY_SCAN_LIMIT', 'Inspect the bounded history before projecting it.')
    candidates = list(query.filter(pk__in=[pk for pk, _ in sizes]))
    selected = {}
    changed = True
    while changed:
        previous = (len(session_ids), len(order_ids), len(item_ids), len(selected))
        for row in candidates:
            path, body = row.operation.get('path', ''), _body(row)
            include = False
            if path == FLOOR_OPEN and str(body.get('id')) in session_ids:
                _opening_time(row)
                table_ids.add(_uuid(body.get('table')))
                include = True
            elif path == ORDER_OPEN and str(body.get('table_session')) in session_ids:
                order_ids.add(_uuid(body.get('id')))
                include = True
            elif match := TRANSFER.fullmatch(path):
                if match[1] in session_ids and not isinstance(body.get('expected_target_session_ids'), list):
                    raise HistoryPending('HISTORY_TRANSFER_ORIGIN_REQUIRED', 'Original destination session identities are required.')
                target_ids = body.get('expected_target_session_ids', [])
                targets = {str(v) for v in target_ids} if isinstance(target_ids, list) else set()
                if body.get('target_session_id'):
                    targets.add(str(body['target_session_id']))
                if match[1] in session_ids or targets & session_ids:
                    session_ids.update({_uuid(match[1]), *(_uuid(v) for v in targets)})
                    table_ids.add(_uuid(body.get('target_table_id')))
                    include = True
            elif match := ORDER_ACTION.fullmatch(path):
                if match[1] in order_ids:
                    include = True
                    for key in ('edge_created_order_item_id', 'edge_replacement_order_item_id'):
                        if body.get(key):
                            item_ids.add(_uuid(body[key]))
                    items = body.get('items', []) if path.endswith('/bulk/') else [body]
                    if '/items/' in path:
                        if not isinstance(items, list):
                            raise HistoryPending('HISTORY_INVALID_BODY', 'Original items must be a list.')
                        item_ids.update(_uuid(item['id']) for item in items if isinstance(item, dict) and item.get('id'))
            elif match := ITEM_ACTION.fullmatch(path):
                include = match[1] in item_ids
            elif match := SESSION_ACTION.fullmatch(path):
                group_tables = body.get('table_ids', [])
                group_tables = {str(v) for v in group_tables} if isinstance(group_tables, list) else set()
                if match[1] in session_ids or group_tables & table_ids:
                    if match[2] or row.operation.get('method') not in {'PATCH', 'PUT'}:
                        raise HistoryPending('HISTORY_UNSUPPORTED_OPERATION', 'This connected floor operation requires an explicit plan.')
                    include = True
            if include:
                selected[row.operation_id] = row
        changed = previous != (len(session_ids), len(order_ids), len(item_ids), len(selected))
    rows = [row for row in candidates if row.operation_id in selected]
    if not rows or len(rows) > 500 or sum(len(str(row.operation)) for row in rows) > 8 * 1024 * 1024:
        raise HistoryPending('HISTORY_COMPONENT_LIMIT', 'History must contain at most 500 bounded operations.')
    openings = {_uuid(_body(row).get('id')) for row in rows if row.operation.get('path') == FLOOR_OPEN}
    if openings != session_ids:
        raise HistoryPending('HISTORY_DEPENDENCY_WAIT', 'Original source and target openings have not all arrived.')
    if not any(row.operation.get('path', '').endswith('/pay/') or row.operation.get('method') == 'DELETE' for row in rows):
        raise HistoryPending('HISTORY_DEPENDENCY_WAIT', 'A terminal original sale or cancellation has not arrived.')
    for row in rows:
        if row.operation.get('body') is not None and not isinstance(row.operation['body'], dict):
            raise HistoryPending('HISTORY_INVALID_BODY', 'An original operation body is not an object.')
        if _hash(row.operation) != row.payload_hash or not row.occurred_at:
            raise HistoryPending('HISTORY_EVIDENCE_CONFLICT', 'An original envelope or occurrence time does not match.')
    return root, rows, session_ids, order_ids, table_ids


def project_historical_floor(*, agent, operation_id, dry_run=True):
    try:
        root, rows, session_ids, order_ids, table_ids = plan_historical_floor(agent=agent, operation_id=operation_id)
        if not rows:
            ids = root.last_result.get('historicalProjection', {}).get('operationIds', [root.operation_id])
            return {'ok': True, 'applied': True, 'operationIds': ids, 'replayed': True}
        scope = HistoricalFloorScope(str(agent.restaurant_id), frozenset(session_ids), frozenset(table_ids))
        with transaction.atomic():
            locked = list(LocalAgentMutationInbox.objects.select_for_update().filter(
                restaurant=agent.restaurant, operation_id__in=[row.operation_id for row in rows],
            ).order_by('pk'))
            if {row.operation_id: (row.payload_hash, row.state) for row in locked} != {
                row.operation_id: (row.payload_hash, row.state) for row in rows
            }:
                raise HistoryPending('HISTORY_CHANGED', 'History changed during planning; re-read it.')
            # Existing paid/cancelled/live records require a separate, reviewed plan.
            if TableSession.objects.filter(pk__in=session_ids).exists() or Order.objects.filter(pk__in=order_ids).exists():
                raise HistoryPending('HISTORY_EXISTING_STATE_CONFLICT', 'Existing session/order state must be reviewed, not replaced.')
            tables = list(DiningTable.objects.select_for_update().filter(
                pk__in=table_ids, hall__zone_or_cabin__restaurant=agent.restaurant,
            ).order_by('pk').values())
            if len(tables) != len(table_ids):
                raise HistoryPending('HISTORY_TABLE_SCOPE_INVALID', 'All tables must belong to this restaurant.')
            start = min(row.occurred_at for row in rows)
            start = min(start, *(_opening_time(row) for row in rows if row.operation.get('path') == FLOOR_OPEN))
            with historical_floor_projection(scope):
                for row in rows:
                    result = LocalAgentMutationProcessor().process(agent=agent, operation=copy.deepcopy(row.operation))
                    if not result.get('ok') or not result.get('applied'):
                        raise HistoryPending('HISTORY_OPERATION_BLOCKED', 'An original operation still requires review.',
                                             operationId=row.operation_id, result=result)
                sessions = list(TableSession.objects.filter(pk__in=session_ids, restaurant=agent.restaurant))
                if len(sessions) != len(session_ids) or any(
                    row.status not in {'closed', 'merged'} or row.closed_at is None for row in sessions
                ) or Order.objects.filter(pk__in=order_ids).exclude(status__in=['closed', 'cancelled']).exists():
                    raise HistoryPending('HISTORY_DEPENDENCY_WAIT', 'History is not fully settled; no projection was committed.')
                end = max(row.closed_at for row in sessions)
                # Conservative interval conflict check also protects grouped tables.
                overlap = TableSession.objects.filter(restaurant=agent.restaurant, opened_at__lt=end).filter(
                    Q(table_id__in=table_ids) | Q(attached_table_links__table_id__in=table_ids)
                ).filter(Q(closed_at__isnull=True) | Q(closed_at__gt=start)).exclude(pk__in=session_ids)
                if overlap.exists():
                    raise HistoryPending('HISTORY_OCCUPANCY_CONFLICT', 'Another original sitting overlaps this historical interval.')
                after = list(DiningTable.objects.filter(pk__in=table_ids).order_by('pk').values())
                if tables != after:
                    raise HistoryPending('HISTORY_LIVE_FLOOR_CHANGED', 'Live table state must remain unchanged.')
            ids = [row.operation_id for row in rows]
            root.refresh_from_db()
            root.last_result = {**root.last_result, 'historicalProjection': {'operationIds': ids}}
            root.save(update_fields=['last_result', 'updated_at'])
            record_security_event(
                event_type='SYNC_HISTORICAL_FLOOR_PROJECTED', restaurant=agent.restaurant,
                result='DRY_RUN' if dry_run else 'APPLIED',
                metadata={'rootOperationId': operation_id, 'operationIds': ids,
                          'originalHashes': {row.operation_id: row.payload_hash for row in rows},
                          'sessionIds': sorted(session_ids), 'newFiscalOrPrint': False},
            )
            if dry_run:
                transaction.set_rollback(True)
            return {'ok': True, 'applied': not dry_run, 'dryRun': dry_run, 'operationIds': ids,
                    'sessionIds': sorted(session_ids), 'newFiscalOrPrint': False}
    except HistoryPending as exc:
        return exc.result


class LocalAgentHistoricalFloorView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]

    def post(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent identity.'}, status=401)
        dry_run = request.data.get('dryRun', request.data.get('dry_run', True))
        if not isinstance(dry_run, bool):
            return Response({'detail': 'dryRun must be a boolean.'}, status=400)
        return Response(project_historical_floor(
            agent=agent, operation_id=str(request.data.get('operationId') or request.data.get('operation_id') or ''),
            dry_run=dry_run,
        ))
