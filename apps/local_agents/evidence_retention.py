"""Bounded, opt-in maintenance. Identity guards and business timestamps are immutable."""
import copy
import hashlib
import re
import time
import uuid
from collections import Counter
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import CharField, Q
from django.db.models.functions import Cast, Length
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from djangorestframework_camel_case.util import underscoreize

from apps.local_agents.evidence_archive import (
    archive_store, assert_outside_transaction, build_bundle, decode_bundle,
)
from apps.local_agents.evidence_store import (
    MIN_BODY_BYTES, REFERENCE_KEY, EvidenceUnavailable, canonical_bytes,
    is_reference, resolve_body, store_body, store_result,
)
from apps.local_agents.models import (
    AgentEvidenceArchive, AgentEvidencePayload, AgentEvidencePolicy,
    LocalAgentMutationAttempt, LocalAgentMutationInbox, LocalAgentMutationReceipt,
)


def _short_transaction():
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '2s'")
            cursor.execute("SET LOCAL statement_timeout = '15s'")


def _after_cursor(queryset, cursor):
    if not cursor:
        return queryset
    created_at = parse_datetime(cursor['created_at'])
    return queryset.filter(Q(created_at__gt=created_at) | Q(created_at=created_at, id__gt=cursor['id']))


def _cursor(obj, source=None):
    return {'created_at': obj.created_at.isoformat(), 'id': str(obj.pk), **({'source': source} if source else {})}


def candidates(restaurant_id, limit, now, cursor=None):
    cutoff = now - timedelta(days=7)
    receipts = LocalAgentMutationReceipt.objects.filter(
        restaurant_id=restaurant_id, response_status__gte=200, response_status__lt=300,
        created_at__lte=cutoff, updated_at__lte=cutoff,
    ).exclude(response_body__has_key=REFERENCE_KEY).annotate(
        evidence_length=Length(Cast('response_body', CharField())),
    ).filter(evidence_length__gte=MIN_BODY_BYTES).order_by('created_at', 'id')
    inboxes = LocalAgentMutationInbox.objects.filter(
        restaurant_id=restaurant_id, state='applied', last_result__ok=True,
        created_at__lte=cutoff, updated_at__lte=cutoff, applied_at__lte=cutoff,
    ).exclude(last_result__body__has_key=REFERENCE_KEY).annotate(
        evidence_length=Length(Cast('last_result__body', CharField())),
    ).filter(evidence_length__gte=MIN_BODY_BYTES).order_by('created_at', 'id')
    sources = [('receipt', receipts), ('inbox', inboxes)]
    cursor = cursor or {}
    selected = []
    for source, queryset in sources:
        if source == 'receipt' and cursor.get('source') == 'inbox':
            continue
        if cursor.get('source') == source:
            queryset = _after_cursor(queryset, cursor)
        rows = list(queryset.only('id', 'created_at', 'operation_id')[:limit - len(selected)])
        selected.extend((row.operation_id, _cursor(row, source)) for row in rows)
        if len(selected) == limit:
            return selected, selected[-1][1]
    # Revisit the beginning next run: previously protected operations may settle.
    return selected, {}


def _journals(restaurant_id, operation_id, lock=False):
    inboxes = LocalAgentMutationInbox.objects
    receipts = LocalAgentMutationReceipt.objects
    if lock:
        inboxes, receipts = inboxes.select_for_update(), receipts.select_for_update()
    # Same lock order as receive_and_apply: Inbox, then Receipt.
    inbox = inboxes.filter(restaurant_id=restaurant_id, operation_id=operation_id).first()
    receipt = receipts.filter(restaurant_id=restaurant_id, operation_id=operation_id).first()
    return inbox, receipt


def _settled(inbox, receipt, cutoff):
    if inbox is not None:
        if (inbox.state != 'applied' or not inbox.last_result.get('ok') or inbox.applied_at is None
                or max(inbox.created_at, inbox.updated_at, inbox.applied_at) > cutoff):
            return False
    if receipt is not None and (not 200 <= receipt.response_status < 300
                                or max(receipt.created_at, receipt.updated_at) > cutoff):
        return False
    return inbox is not None or receipt is not None


def compact_operation(restaurant_id, operation_id, now, *, dry_run):
    with transaction.atomic():
        _short_transaction()
        inbox, receipt = _journals(restaurant_id, operation_id, lock=not dry_run)
        if not _settled(inbox, receipt, now - timedelta(days=7)):
            return {'skipped': 'not_settled'}
        attempts = list(LocalAgentMutationAttempt.objects.filter(
            inbox=inbox, created_at__lte=now - timedelta(days=7),
        ).order_by('id')[:1001]) if inbox is not None else []
        if len(attempts) > 1000:
            return {'skipped': 'attempt_limit'}
        fields = []
        if receipt is not None:
            fields.append((receipt, 'response_body', receipt.response_body))
        if inbox is not None:
            fields.append((inbox, 'last_result', inbox.last_result))
        for attempt in attempts:
            # Never replace prior failures/conflicts/resolutions with the latest body.
            if attempt.result.get('ok') and attempt.payload_hash == inbox.payload_hash:
                fields.append((attempt, 'result', attempt.result))
        before, after, rows = 0, 0, 0
        for obj, field, value in fields:
            body = value if field == 'response_body' else value.get('body')
            if is_reference(body) or len(canonical_bytes(body)) < MIN_BODY_BYTES:
                continue
            before += len(canonical_bytes(value))
            if dry_run:
                rows += 1
                continue
            if field == 'response_body':
                replacement = store_body(restaurant_id=restaurant_id, operation_id=operation_id, body=body, force=True)
            else:
                replacement = store_result(restaurant_id=restaurant_id, operation_id=operation_id, result=value, force=True)
            # Explicit JSON-only UPDATE: auto_now and immutable hashes remain untouched.
            type(obj).objects.filter(pk=obj.pk).update(**{field: replacement})
            after += len(canonical_bytes(replacement))
            rows += 1
        return {'rows': rows, 'inline_bytes_before': before, 'inline_bytes_after': after}


def branch_cold_blocker(restaurant_id):
    from apps.billing.models import Payment, Receipt
    from apps.printing.models import PrintJob

    # Conservative first rollout: any unresolved event protects every ancestor in
    # this restaurant, including legacy chains and certified deferred ancestors.
    if LocalAgentMutationInbox.objects.filter(restaurant_id=restaurant_id).exclude(state__in=['applied', 'resolved']).exists():
        return 'unresolved_inbox'
    if Payment.objects.filter(order__restaurant_id=restaurant_id, status='pending').exists():
        return 'unsettled_payment'
    if Receipt.objects.filter(order__restaurant_id=restaurant_id, kind__in=['fiscal', 'refund']).exclude(status='sent').exists():
        return 'unsettled_fiscal_receipt'
    if PrintJob.objects.filter(restaurant_id=restaurant_id).exclude(status='succeeded').exists():
        return 'unfinished_print'
    return ''


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _closed_session(restaurant_id, session_id, cutoff):
    from apps.floor.models import TableSession

    visited = set()
    while session_id and session_id not in visited and len(visited) < 128:
        visited.add(session_id)
        session = TableSession.objects.filter(pk=session_id, restaurant_id=restaurant_id).first()
        if (session is None or session.closed_at is None
                or max(session.closed_at, session.updated_at) > cutoff):
            return False
        if session.status == 'closed':
            return True
        if session.status != 'merged':
            return False
        session_id = session.merged_into_id
    return False


def cold_eligibility(payload, now):
    from apps.billing.models import CashShift, FiscalShiftSession, Payment, PaymentRefund
    from apps.sales.models import Order, OrderItem

    inbox, receipt = _journals(payload.restaurant_id, payload.operation_id)
    operation = inbox.operation if inbox else {'path': receipt.path, 'method': receipt.method, 'body': {}} if receipt else {}
    path = str(operation.get('path') or '')
    financial = '/billing/' in path
    cutoff = now - timedelta(days=30 if financial else 14)
    if not _settled(inbox, receipt, cutoff):
        return 'not_old_and_settled'
    # Only current successful bodies can go cold. Historical distinct Attempt
    # bodies remain hot; failures/resolutions remain inline in their journals.
    current = []
    if inbox:
        current.append(inbox.last_result.get('body'))
    if receipt:
        current.append(receipt.response_body)
    if not any(is_reference(body) and body.get(REFERENCE_KEY, {}).get('id') == str(payload.pk) for body in current):
        return 'historical_attempt'
    if inbox and inbox.attempts.filter(updated_at__gt=cutoff).exists():
        return 'recent_attempt'
    body = underscoreize(operation.get('body') or {})
    response = underscoreize((payload.content or {}).get('body') or {})
    if not isinstance(body, dict) or not isinstance(response, dict):
        return 'unproven_resource'
    match = re.search(r'/(?:sales|billing)/orders/([0-9a-f-]{36})(?:/|$)', path)
    order_id = _uuid(match[1]) if match else _uuid(body.get('order') or body.get('order_id'))
    if path.rstrip('/') == '/api/v1/pos/sales/orders':
        order_id = _uuid(body.get('id') or response.get('id'))
    item_match = re.search(r'/sales/order-items/([0-9a-f-]{36})(?:/|$)', path)
    if item_match:
        order_id = OrderItem.objects.filter(pk=_uuid(item_match[1]), order__restaurant_id=payload.restaurant_id).values_list('order_id', flat=True).first()
    if order_id:
        order = Order.objects.filter(pk=order_id, restaurant_id=payload.restaurant_id).first()
        if (order is None or order.status not in {'closed', 'cancelled'} or order.closed_at is None
                or max(order.closed_at, order.updated_at) > cutoff):
            return 'order_not_closed'
        if order.table_session_id and not _closed_session(payload.restaurant_id, order.table_session_id, cutoff):
            return 'session_not_closed'
        if Payment.objects.filter(order=order).exclude(status__in=['succeeded', 'failed']).exists():
            return 'order_payment_unsettled'
        if Payment.objects.filter(order=order).exclude(cash_shift__isnull=True).exclude(cash_shift__status='closed').exists():
            return 'cash_shift_not_closed'
        if PaymentRefund.objects.filter(payment__order=order).filter(
            Q(updated_at__gt=cutoff) | (Q(cash_shift__isnull=False) & ~Q(cash_shift__status='closed')),
        ).exists():
            return 'refund_not_settled_and_old'
        return ''
    session_match = re.search(r'/floor/table-sessions/([0-9a-f-]{36})(?:/|$)', path)
    session_id = _uuid(session_match[1]) if session_match else _uuid(body.get('table_session'))
    if path.rstrip('/') == '/api/v1/pos/floor/table-sessions':
        session_id = _uuid(body.get('id') or response.get('id'))
    if session_id:
        return '' if _closed_session(payload.restaurant_id, session_id, cutoff) else 'session_not_closed'
    if '/billing/shifts/' in path:
        shift_id = _uuid(body.get('edge_cash_shift_id'))
        return '' if shift_id and CashShift.objects.filter(pk=shift_id, cash_desk__restaurant_id=payload.restaurant_id, status='closed', closed_at__isnull=False).exists() else 'cash_shift_unproven'
    if '/billing/fiscal-shifts/' in path:
        session_id = str(body.get('fiscal_session_id') or operation.get('fiscalSessionId') or operation.get('fiscal_session_id') or '')
        return '' if session_id and FiscalShiftSession.objects.filter(restaurant_id=payload.restaurant_id, edge_session_id=session_id, status='closed', closed_at__isnull=False).exists() else 'fiscal_shift_unproven'
    return 'unproven_resource'


def archive_payloads(restaurant_id, now, limit, deadline, *, dry_run, cursor=None):
    assert_outside_transaction()
    blocker = branch_cold_blocker(restaurant_id)
    if blocker:
        return {'archived': 0, 'blocked': blocker}
    reasons, selected = Counter(), []
    queryset = AgentEvidencePayload.objects.filter(
        restaurant_id=restaurant_id, content__isnull=False, archived_at__isnull=True,
    ).order_by('created_at', 'id')
    queryset = _after_cursor(queryset, cursor) if cursor else queryset
    with transaction.atomic():
        _short_transaction()
        batch = list(queryset[:limit * 4])
    next_cursor = cursor or {}
    for payload in batch:
        if time.monotonic() >= deadline or sum(reasons.values()) + len(selected) >= limit * 4:
            break
        next_cursor = _cursor(payload)
        reason = cold_eligibility(payload, now)
        if reason:
            reasons[reason] += 1
            continue
        selected.append(payload)
        if len(selected) >= limit:
            break
    else:
        if len(batch) < limit * 4:
            next_cursor = {}
    report = {'eligible': len(selected), 'skips': dict(reasons), 'archived': 0, 'cursor': next_cursor}
    if dry_run or not selected:
        return report
    data = build_bundle(selected)
    manifest = AgentEvidenceArchive(
        restaurant_id=restaurant_id, backend=archive_store().name,
        checksum=hashlib.sha256(data).hexdigest(), byte_length=len(data), record_count=len(selected),
        verified_at=timezone.now(),
    )
    manifest.object_key = f'v1/{restaurant_id}/{manifest.pk}.jsonl.gz'
    store = archive_store(manifest.backend)
    store.put(manifest.object_key, data)
    verified = decode_bundle(data=store.get(manifest.object_key), archive=manifest)
    if any(verified.get(str(payload.pk)) != payload.content for payload in selected):
        raise EvidenceUnavailable('Archive readback differs from the original payloads.')
    # A crash before here leaves hot bodies intact and only an unreferenced object.
    manifest.verified_at = timezone.now()
    manifest.save(force_insert=True)
    for original in selected:
        if time.monotonic() >= deadline:
            break
        with transaction.atomic():
            _short_transaction()
            _journals(restaurant_id, original.operation_id, lock=True)
            payload = AgentEvidencePayload.objects.select_for_update().get(pk=original.pk)
            policy = AgentEvidencePolicy.objects.get(restaurant_id=restaurant_id)
            if (not policy.archive_enabled or not policy.compaction_enabled
                    or payload.content != original.content or payload.checksum != original.checksum
                    or payload.archive_id or branch_cold_blocker(restaurant_id) or cold_eligibility(payload, now)):
                report.setdefault('changed_before_finalize', 0)
                report['changed_before_finalize'] += 1
                continue
            # Do not touch the Inbox, Receipt, Attempt or their business timestamps.
            AgentEvidencePayload.objects.filter(pk=payload.pk).update(
                content=None, archive=manifest, archived_at=timezone.now(),
            )
            report['archived'] += 1
    report.update(bundle_bytes=len(data), manifest_id=str(manifest.pk))
    return report


def run_retention(*, restaurant_id, apply=False, archive=False, batch_size=500, max_seconds=120):
    assert_outside_transaction()
    if not 1 <= batch_size <= 1000 or not 1 <= max_seconds <= 240:
        raise ValueError('batch_size must be 1..1000 and max_seconds 1..240.')
    now, started = timezone.now(), time.monotonic()
    deadline = started + max_seconds
    token = uuid.uuid4()
    prior_report = AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id).values_list('last_report', flat=True).first() or {}
    if apply:
        with transaction.atomic():
            _short_transaction()
            policy = AgentEvidencePolicy.objects.select_for_update().filter(restaurant_id=restaurant_id).first()
            if policy is None or not policy.compaction_enabled or (archive and not policy.archive_enabled):
                raise ValueError('This restaurant is not allowlisted for the requested maintenance.')
            if policy.lease_until and policy.lease_until > now:
                return {'restaurant_id': str(restaurant_id), 'busy': True}
            AgentEvidencePolicy.objects.filter(pk=policy.pk).update(lease_token=token, lease_until=now + timedelta(minutes=6))
    report = {'restaurant_id': str(restaurant_id), 'dry_run': not apply, 'operations': 0, 'rows': 0,
              'inline_bytes_before': 0, 'inline_bytes_after': 0, 'skips': {},
              'compaction_cursor': prior_report.get('compaction_cursor', {})}
    try:
        with transaction.atomic():
            _short_transaction()
            ids, end_cursor = candidates(restaurant_id, batch_size, now, report['compaction_cursor'])
        for operation_id, position in ids:
            if time.monotonic() >= deadline:
                break
            if apply and not AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id, compaction_enabled=True).exists():
                break
            outcome = compact_operation(restaurant_id, operation_id, now, dry_run=not apply)
            report['compaction_cursor'] = position
            if outcome.get('skipped'):
                report['skips'][outcome['skipped']] = report['skips'].get(outcome['skipped'], 0) + 1
                continue
            report['operations'] += 1
            for key in ('rows', 'inline_bytes_before', 'inline_bytes_after'):
                report[key] += outcome[key]
        else:
            report['compaction_cursor'] = end_cursor
        if archive:
            report['archive'] = archive_payloads(restaurant_id, now, batch_size, deadline, dry_run=not apply,
                                                 cursor=prior_report.get('archive', {}).get('cursor'))
        return report
    except Exception as error:
        report['error'] = type(error).__name__
        if apply:
            AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id, lease_token=token).update(schedule_enabled=False)
        raise
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 3)
        if apply:
            AgentEvidencePolicy.objects.filter(restaurant_id=restaurant_id, lease_token=token).update(
                lease_token=None, lease_until=None, last_run_at=timezone.now(), last_report=report,
            )


def rehydrate_operation(restaurant_id, operation_id):
    """Rollback preparation: hydrate before locking; readers must remain deployed."""
    assert_outside_transaction()
    inbox, receipt = _journals(restaurant_id, operation_id)
    fields = [(receipt, 'response_body')] if receipt else []
    if inbox:
        fields.append((inbox, 'last_result'))
        fields.extend((attempt, 'result') for attempt in inbox.attempts.all())
    prepared = []
    for obj, field in fields:
        original = getattr(obj, field)
        body = original if field == 'response_body' else original.get('body')
        if not is_reference(body):
            continue
        resolved = resolve_body(restaurant_id=restaurant_id, operation_id=operation_id, body=body)
        replacement = resolved if field == 'response_body' else {**copy.deepcopy(original), 'body': resolved}
        prepared.append((obj, field, original, replacement))
    with transaction.atomic():
        _short_transaction()
        _journals(restaurant_id, operation_id, lock=True)
        for obj, field, original, replacement in prepared:
            if not type(obj).objects.filter(pk=obj.pk, **{field: original}).update(**{field: replacement}):
                raise EvidenceUnavailable('Journal changed during rehydration; retry before rolling back code.')
    return len(prepared)


def scheduled_retention():
    reports = []
    deadline = time.monotonic() + 220
    # Explicit opt-in only. No schedule is registered by AppConfig or a migration.
    for policy in AgentEvidencePolicy.objects.filter(schedule_enabled=True, compaction_enabled=True)[:10]:
        if time.monotonic() + 20 > deadline:
            break
        reports.append(run_retention(restaurant_id=policy.restaurant_id, apply=True, archive=policy.archive_enabled, batch_size=100, max_seconds=20))
    return reports
