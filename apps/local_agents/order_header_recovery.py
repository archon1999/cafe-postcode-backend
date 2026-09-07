"""Recover the exact legacy closed-session order rejection from durable evidence."""
import copy
import json
import uuid
from decimal import Decimal

from django.db import transaction
from djangorestframework_camel_case.util import camelize, underscoreize
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.models import SecurityEvent
from apps.floor.models import TableSession
from apps.local_agents.authentication import authenticate_local_agent
from apps.local_agents.models import LocalAgentCommand, LocalAgentMutationInbox, LocalAgentMutationReceipt
from apps.local_agents.mutation_inbox import _hash
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.local_agents.mutation_reconciliation import request_hash
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.sales.serializers import OrderSerializer
from apps.sales.services.state import OrderStateService
from apps.users.models import User
from common.api.throttling import LocalAgentRateThrottle


def recover_order_header(*, agent, operation, reason, request_id=''):
    reason = str(reason or '').strip()
    if not isinstance(operation, dict) or not reason or len(reason) > 500:
        raise ValidationError('Original operation and a reason up to 500 characters are required.')
    operation_id = str(operation.get('operationId') or operation.get('operation_id') or '')
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, f'postcode:order-header-recovery:{agent.restaurant_id}:{operation_id}')
    with transaction.atomic():
        inbox = LocalAgentMutationInbox.objects.select_for_update().filter(
            restaurant_id=agent.restaurant_id, operation_id=operation_id,
        ).first()
        if inbox is None or inbox.payload_hash != _hash(operation):
            raise ValidationError('Matching original Agent and backend evidence is required.')
        original = copy.deepcopy(inbox.operation)
        body = underscoreize(original.get('body') or {})
        if (original.get('method') != 'POST' or original.get('path') != '/api/v1/pos/sales/orders/'
                or body.get('channel') != 'hall'
                or set(body) - {'id', 'table_session', 'channel', 'note', 'display_name', 'guest_count'}):
            raise ValidationError('Only the original hall order header is recoverable here.')
        try:
            order_id, session_id = uuid.UUID(str(body.get('id'))), uuid.UUID(str(body.get('table_session')))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError('Original order and table-session UUIDs are required.')
        event = SecurityEvent.objects.filter(pk=event_id, restaurant_id=agent.restaurant_id).first()
        if event is not None:
            if inbox.state != LocalAgentMutationInbox.State.APPLIED or not Order.objects.filter(
                pk=order_id, restaurant_id=agent.restaurant_id, table_session_id=session_id,
            ).exists():
                raise ValidationError('Recovered evidence is inconsistent; inspect it before retrying.')
            return {'ok': True, 'applied': True, 'operationId': operation_id, 'orderId': str(order_id),
                    'auditId': str(event_id), 'replayed': True, 'payloadHash': inbox.payload_hash}
        previous = copy.deepcopy(inbox.last_result)
        rejection = underscoreize(previous.get('body') or {})
        if (inbox.state != LocalAgentMutationInbox.State.NEEDS_REVIEW or previous.get('ok')
                or previous.get('retryable') or previous.get('status') != 400
                or not isinstance(rejection, dict) or set(rejection) != {'table_session'}
                or rejection['table_session'] not in (
                    'This table session is no longer active.', ['This table session is no longer active.'])):
            raise ValidationError('The original closed-session rejection must be the only validation failure.')
        if LocalAgentMutationReceipt.objects.filter(operation_id=operation_id).exists() or Order.objects.filter(pk=order_id).exists():
            raise ValidationError('An existing order or receipt must be inspected, not replaced.')
        user_id = original.get('userId') or original.get('user_id')
        user = User.objects.filter(pk=user_id, restaurant_profile__restaurant_id=agent.restaurant_id, is_active=True).first()
        if user is None or not user.can_access_pos_ui or 'pos_tables.manage' not in user.permission_codes:
            raise ValidationError('The original restaurant user must still be authorized to create hall orders.')
        occurred_at, error = LocalAgentMutationProcessor._parse_occurred_at(
            original.get('occurredAt') or original.get('occurred_at'))
        if error or occurred_at is None or occurred_at != inbox.occurred_at:
            raise ValidationError('The original durable occurrence time is required.')
        restaurant = Restaurant.objects.select_for_update().get(pk=agent.restaurant_id)
        session = TableSession.objects.select_for_update().filter(
            pk=session_id, restaurant=restaurant, status=TableSession.Status.CLOSED,
            closed_at__isnull=False, merged_into__isnull=True,
        ).first()
        if session is None or session.closed_at > occurred_at or session.opened_at > occurred_at:
            raise ValidationError('The original session must have been closed, without a merge, before this order.')
        OrderStateService.ensure_table_session_matches_restaurant(table_session=session, restaurant=restaurant)
        if session.orders.exclude(status__in=[Order.Status.CLOSED, Order.Status.CANCELLED]).exists():
            raise ValidationError('A conflicting active order already uses this historical session.')
        guest_count = body.get('guest_count', session.guest_count)
        if (isinstance(guest_count, bool) or not isinstance(guest_count, int) or not 1 <= guest_count <= 32767
                or not isinstance(body.get('note', ''), str) or not isinstance(body.get('display_name', ''), str)
                or len(body.get('display_name', '')) > Order._meta.get_field('display_name').max_length):
            raise ValidationError('Original order header fields are invalid.')
        restaurant.last_order_number += 1
        restaurant.save(update_fields=['last_order_number', 'updated_at'])
        order = Order.objects.create(
            id=order_id, restaurant=restaurant, table_session=session, opened_by=user,
            order_number=restaurant.last_order_number, display_name=body.get('display_name', ''),
            channel=Order.Channel.HALL, note=body.get('note', ''), guest_count=guest_count,
            status=Order.Status.OPEN,
        )
        # Even an empty historical snapshot is authoritative; do not capture today's fees.
        snapshot = copy.deepcopy(session.service_fee_snapshot)
        percentages = {item['scope']: Decimal(str(item.get('percent') or 0))
                       for item in snapshot if item.get('mode') == 'percentage'}
        Order.objects.filter(pk=order.pk).update(
            created_at=occurred_at, service_fee_snapshot=snapshot, service_fee_started_at=session.opened_at,
            restaurant_service_fee_percent=percentages.get('restaurant', 0),
            hall_service_fee_percent=percentages.get('hall', 0), table_service_fee_percent=percentages.get('table', 0),
        )
        order.refresh_from_db()
        response = json.loads(json.dumps(camelize(OrderSerializer(order).data), default=str))
        digest = request_hash(user_id=str(user.pk), method=original['method'], path=original['path'], body=original['body'])
        command = LocalAgentCommand.objects.filter(
            agent=agent, pk=request_id, command_type='support.execute', payload__name='sync.reconcile',
        ).first() if request_id else None
        SecurityEvent.objects.create(
            id=event_id, restaurant=restaurant, actor_id=command.requested_by_id if command else None,
            event_type='sync.order_header.recovered', severity=SecurityEvent.Severity.MEDIUM,
            result='header_recovered', request_id=request_id,
            metadata={'operationId': operation_id, 'reason': reason, 'agentId': str(agent.pk),
                      'originalInboxEnvelope': original, 'originalInboxHash': inbox.payload_hash,
                      'originalBackendResult': previous, 'originalRequestHash': digest,
                      'historicalSessionBefore': {'status': session.status, 'closedAt': session.closed_at.isoformat()},
                      'canonicalResponse': response, 'noFinancialOperationPerformed': True},
        )
        LocalAgentMutationReceipt.objects.create(
            restaurant=restaurant, operation_id=operation_id, user_id=user.pk, method=original['method'],
            path=original['path'], request_hash=digest, response_status=201, response_body=response,
        )
        result = LocalAgentMutationProcessor().process(agent=agent, operation=original)
        if not result.get('ok') or not result.get('applied') or not result.get('replayed'):
            raise ValidationError('Original dependencies or device authorization still prevent replay; no repair was committed.')
        return {'ok': True, 'applied': True, 'operationId': operation_id, 'orderId': str(order_id),
                'auditId': str(event_id), 'replayed': False, 'payloadHash': inbox.payload_hash}


class LocalAgentOrderHeaderRecoveryView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LocalAgentRateThrottle]

    def post(self, request):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent identity.'}, status=401)
        request_id = str(request.data.get('requestId') or request.data.get('request_id') or '')
        if request_id:
            try:
                request_id = str(uuid.UUID(request_id))
            except (ValueError, TypeError, AttributeError):
                raise ValidationError('Command request UUID is invalid.')
        return Response(recover_order_header(
            agent=agent, operation=request.data.get('operation'), reason=request.data.get('reason'), request_id=request_id,
        ))
