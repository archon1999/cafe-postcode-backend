import copy
import hashlib
import json
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.local_agents.models import LocalAgentMutationAttempt, LocalAgentMutationInbox
from apps.local_agents.mutation_results import mutation_error_result

logger = logging.getLogger(__name__)


def financial_event_metadata(operation):
    """Accept both the wire envelope and DRF CamelCaseJSONParser output."""
    def value(*names, default=None):
        return next((operation[name] for name in names if name in operation), default)

    return {
        'eventVersion': value('eventVersion', 'event_version', 'financialEventVersion', 'financial_event_version', default=1),
        'ownerEpoch': value('ownerEpoch', 'owner_epoch', default='') or '',
        'sequence': value('sequence', 'localSequence', 'local_sequence'),
        'dependsOn': value('dependsOn', 'depends_on', default=[]) or [],
        'fiscalSessionId': value('fiscalSessionId', 'fiscal_session_id', default='') or '',
        'eventType': value('eventType', 'event_type', default='') or '',
    }


def _hash(operation):
    # Transport retry counters are not event identity. Keep the raw first
    # envelope separately while hashing only immutable semantic facts.
    canonical = {
        "operationId": operation.get("operationId", operation.get("operation_id")),
        "userId": operation.get("userId", operation.get("user_id")),
        "deviceId": operation.get("deviceId", operation.get("device_id")),
        "method": str(operation.get("method") or "").upper(),
        "path": operation.get("path"),
        "body": operation.get("body") or {},
        "occurredAt": operation.get("occurredAt", operation.get("occurred_at")),
        **financial_event_metadata(operation),
    }
    canonical['dependsOn'] = sorted(canonical['dependsOn'])
    return hashlib.sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _metadata(inbox, result):
    return {
        **result,
        "durablyReceived": True,
        "applied": inbox.state == "applied",
        "inboxState": inbox.state,
        "payloadHash": inbox.payload_hash,
    }


def receive_and_apply(*, agent, operation, apply):
    """Reserve in autocommit, then lock/apply/ack atomically; no external I/O here.

    The raw original envelope survives any later validation/projection rollback.
    Historical epochs may upload facts; this endpoint never grants device ownership.
    """
    operation = copy.deepcopy(operation)
    operation_id = str(
        operation.get("operationId") or operation.get("operation_id") or ""
    ).strip()
    metadata = financial_event_metadata(operation)
    epoch = str(metadata['ownerEpoch'])
    sequence = metadata['sequence']
    version = metadata['eventVersion']
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or not 1 <= version <= 2
    ):
        return mutation_error_result(
            operation_id=operation_id,
            response_status=400,
            error="Unsupported event version.",
            code="INVALID_EVENT_VERSION",
        )
    if sequence is not None and (
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
    ):
        return mutation_error_result(
            operation_id=operation_id,
            response_status=400,
            error="sequence must be a positive integer.",
            code="INVALID_SEQUENCE",
        )
    dependencies = metadata['dependsOn']
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or len(item) > 128 or item == operation_id
        for item in dependencies
    ):
        return mutation_error_result(
            operation_id=operation_id,
            response_status=400,
            error="dependsOn must contain other operation IDs.",
            code="INVALID_DEPENDENCIES",
        )
    if (
        len(epoch) > 128
        or (sequence is not None and not epoch)
        or (version == 2 and (sequence is None or not epoch))
    ):
        return mutation_error_result(
            operation_id=operation_id,
            response_status=400,
            error="Sequenced events require ownerEpoch.",
            code="INVALID_OWNER_EPOCH",
        )
    digest = _hash(operation)
    occurred_at = parse_datetime(
        str(operation.get("occurredAt") or operation.get("occurred_at") or "")
    )
    if occurred_at is not None and timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at)
    try:
        inbox, _ = LocalAgentMutationInbox.objects.get_or_create(
            operation_id=operation_id,
            defaults={
                "restaurant": agent.restaurant,
                "payload_hash": digest,
                "operation": operation,
                "owner_epoch": epoch,
                "sequence": sequence,
                "depends_on": dependencies,
                "event_version": version,
                "occurred_at": occurred_at,
            },
        )
    except IntegrityError:
        inbox = LocalAgentMutationInbox.objects.filter(
            operation_id=operation_id
        ).first()
        if inbox is None:
            # Preserve competing sequence evidence against its already-reserved owner.
            inbox = LocalAgentMutationInbox.objects.get(
                restaurant=agent.restaurant, owner_epoch=epoch, sequence=sequence
            )
            result = mutation_error_result(
                operation_id=operation_id,
                response_status=409,
                error="Sequence already belongs to another event.",
                code="EVENT_SEQUENCE_CONFLICT",
                classification="quarantined",
            )
            LocalAgentMutationAttempt.objects.create(
                inbox=inbox, payload_hash=digest, operation=operation, result=result
            )
            return {
                **result,
                "durablyReceived": True,
                "applied": False,
                "inboxState": "conflict",
                "payloadHash": digest,
            }

    with transaction.atomic():
        inbox = LocalAgentMutationInbox.objects.select_for_update().get(pk=inbox.pk)
        if inbox.restaurant_id != agent.restaurant_id or inbox.payload_hash != digest:
            result = mutation_error_result(
                operation_id=operation_id,
                response_status=409,
                error="Operation ID belongs to different immutable evidence.",
                code="OPERATION_ID_CONFLICT",
                classification="quarantined",
            )
            if inbox.restaurant_id == agent.restaurant_id:
                LocalAgentMutationAttempt.objects.create(
                    inbox=inbox, payload_hash=digest, operation=operation, result=result
                )
            return {
                **result,
                "durablyReceived": inbox.restaurant_id == agent.restaurant_id,
                "applied": False,
                "inboxState": "conflict",
                "payloadHash": digest,
            }
        if inbox.state == LocalAgentMutationInbox.State.APPLIED:
            return _metadata(inbox, {**inbox.last_result, "replayed": True})
        present = set(
            LocalAgentMutationInbox.objects.filter(
                restaurant=agent.restaurant,
                operation_id__in=dependencies,
                state="applied",
            ).values_list("operation_id", flat=True)
        )
        # Legacy successful mutation receipts remain valid causal dependencies.
        from apps.local_agents.models import LocalAgentMutationReceipt

        present.update(
            LocalAgentMutationReceipt.objects.filter(
                restaurant=agent.restaurant,
                operation_id__in=dependencies,
                response_status__gte=200,
                response_status__lt=300,
            ).values_list("operation_id", flat=True)
        )
        missing = [item for item in dependencies if item not in present]
        if missing:
            result = mutation_error_result(
                operation_id=operation_id,
                response_status=409,
                error="Earlier operations have not been applied.",
                code="MISSING_DEPENDENCIES",
                retryable=True,
            )
            result["missingDependencies"] = missing
        else:
            try:
                with transaction.atomic():
                    result = apply(operation)
                    body = result.get("body")
                    if isinstance(body, dict) and body.get("code") in {
                        "EDGE_CASH_SHIFT_NOT_FOUND",
                        "CASH_SHIFT_NOT_SYNCHRONIZED",
                        "FISCAL_CLOSE_DEPENDENCY_PENDING",
                        "SHIFT_PREDECESSOR_PENDING",
                    }:
                        result.update(retryable=True, classification="retry")
                    # API validation failures may have written intermediary state.
                    # Keep received evidence, but never commit a partial DB projection.
                    if not result.get("ok"):
                        transaction.set_rollback(True)
            except Exception:
                logger.exception(
                    "Mutation projection failed", extra={"operation_id": operation_id}
                )
                result = mutation_error_result(
                    operation_id=operation_id,
                    response_status=503,
                    error="Projection failed; received evidence is retained.",
                    code="PROJECTION_RETRY",
                    retryable=True,
                )
        inbox.state = (
            "applied"
            if result.get("ok")
            else ("received" if result.get("retryable") else "needs_review")
        )
        inbox.applied_at = timezone.now() if result.get("ok") else None
        inbox.last_result = result
        inbox.save(update_fields=["state", "applied_at", "last_result", "updated_at"])
        LocalAgentMutationAttempt.objects.create(
            inbox=inbox, payload_hash=digest, result=result
        )
        return _metadata(inbox, result)
