"""Explicit cancellation of rejected evidence, acknowledged before local release."""
import copy
from uuid import UUID

from django.db import transaction
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.models import LocalAgentMutationAttempt, LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import _hash, _metadata
from common.api.throttling import LocalAgentRateThrottle


def resolve_rejected_mutation(*, agent, operation, reason):
    operation_id = str(operation.get('operationId') or operation.get('operation_id') or '').strip()
    if not operation_id or not reason or len(reason) > 500:
        raise ValidationError('Operation ID and a reason (up to 500 characters) are required.')
    with transaction.atomic():
        inbox = LocalAgentMutationInbox.objects.select_for_update().filter(
            restaurant=agent.restaurant, operation_id=operation_id,
        ).first()
        if inbox is None or inbox.payload_hash != _hash(operation):
            raise ValidationError('Matching original received evidence is required.')
        if inbox.state == LocalAgentMutationInbox.State.RESOLVED:
            return _metadata(inbox, {**inbox.last_result, 'replayed': True})
        original = copy.deepcopy(inbox.last_result)
        if (inbox.state != LocalAgentMutationInbox.State.NEEDS_REVIEW
                or original.get('ok') or original.get('retryable')
                or original.get('status') not in {400, 404, 422}):
            raise ValidationError('Only definitively rejected operations can be cancelled. Reconcile other results first.')
        path = str(inbox.operation.get('path') or '')
        # Cancellation is never a substitute for receipt/payment reconciliation.
        if '/billing/' in path:
            if path != '/api/v1/pos/billing/shifts/open/':
                raise ValidationError('Payment, refund and fiscal-close evidence must be reconciled, not cancelled.')
            from apps.billing.models import CashShift
            body = inbox.operation.get('body') or {}
            try:
                shift_id = UUID(str(body.get('edgeCashShiftId') or body.get('edge_cash_shift_id') or ''))
            except (ValueError, TypeError):
                raise ValidationError('The rejected shift identity is required.')
            if CashShift.objects.filter(pk=shift_id).exists():
                raise ValidationError('A persisted shift cannot be cancelled through outbox resolution.')
        result = {
            'ok': True, 'status': 200, 'operationId': operation_id,
            'code': 'MUTATION_CANCELLED', 'classification': 'resolved',
            'body': {'disposition': 'cancelled', 'businessOperationApplied': False, 'reason': reason},
        }
        LocalAgentMutationAttempt.objects.create(
            inbox=inbox, payload_hash=inbox.payload_hash,
            result={'resolution': result, 'previousResult': original, 'agentId': str(agent.pk)},
        )
        inbox.state = LocalAgentMutationInbox.State.RESOLVED
        inbox.last_result = result
        # applied_at deliberately stays null: cancellation did not apply a sale.
        inbox.save(update_fields=['state', 'last_result', 'updated_at'])
        return _metadata(inbox, result)


class LocalAgentMutationResolveView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]

    def post(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=401)
        operation = request.data.get('operation')
        if not isinstance(operation, dict):
            raise ValidationError('Original operation is required.')
        return Response(resolve_rejected_mutation(
            agent=agent, operation=operation, reason=str(request.data.get('reason') or '').strip(),
        ))
