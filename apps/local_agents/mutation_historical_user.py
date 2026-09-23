"""Preserve an archived cashier's already recorded offline work.

This only affects trusted Local Agent projection. It never changes the user's
stored active flag or permits PIN/JWT login after archival.
"""

import re

from django.db.models import Q

from apps.local_agents.models import LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import _hash, financial_event_metadata
from apps.users.models import User
from apps.users.models.employee_profile import EmployeeProfile


_ORDER_PATH = re.compile(r'^/api/v1/pos/sales/orders/(?P<order_id>[0-9a-f-]+)/$')
_ORDER_ITEM_CREATE = re.compile(r'^/api/v1/pos/sales/orders/(?P<order_id>[0-9a-f-]+)/items/$')
_ORDER_SUBMIT = re.compile(r'^/api/v1/pos/sales/orders/(?P<order_id>[0-9a-f-]+)/(?:submit|serve-ready)/$')
_ORDER_ITEM_DELETE = re.compile(r'^/api/v1/pos/sales/orders/items/(?P<item_id>[0-9a-f-]+)/$')


def _historical_order_id(*, agent, operation):
    method = str(operation.get('method') or '').upper()
    path = str(operation.get('path') or '')
    if method == 'POST':
        match = _ORDER_ITEM_CREATE.fullmatch(path) or _ORDER_SUBMIT.fullmatch(path)
    elif method == 'PATCH':
        match = _ORDER_PATH.fullmatch(path)
    elif method == 'DELETE':
        match = _ORDER_ITEM_DELETE.fullmatch(path)
        if match:
            from apps.sales.models import OrderItem

            order_id = OrderItem.objects.filter(
                pk=match.group('item_id'), order__restaurant=agent.restaurant
            ).values_list('order_id', flat=True).first()
            return str(order_id) if order_id else None
    else:
        return None
    return match.group('order_id') if match else None


def _belongs_to_proven_historical_order(*, agent, operation, user_id, device_id, occurred_at):
    """Admit old unsequenced order edits only under their applied original header.

    Older Agent versions had no owner epoch. The header's durable, applied
    envelope supplies a narrower provenance boundary than a backdated clock.
    """
    order_id = _historical_order_id(agent=agent, operation=operation)
    if order_id is None:
        return False

    from apps.sales.models import Order

    if not Order.objects.filter(
        pk=order_id, restaurant=agent.restaurant, opened_by_id=user_id
    ).exists():
        return False

    headers = LocalAgentMutationInbox.objects.filter(
        restaurant=agent.restaurant,
        state=LocalAgentMutationInbox.State.APPLIED,
        operation__body__id=order_id,
    )
    for header in headers:
        original = header.operation
        if (str(original.get('method') or '').upper() != 'POST'
                or original.get('path') != '/api/v1/pos/sales/orders/'
                or str(original.get('userId') or original.get('user_id') or '') != user_id
                or str(original.get('deviceId') or original.get('device_id') or '') != device_id
                or header.occurred_at is None
                or header.occurred_at > occurred_at):
            continue
        return True
    return False


def archived_historical_pos_user(*, agent, operation, user_id, device_id, occurred_at):
    if occurred_at is None or not device_id:
        return None
    user = (
        User.objects.filter(
            id=user_id,
            restaurant_profile__restaurant=agent.restaurant,
            is_active=False,
            employee_profile__employment_status=EmployeeProfile.EmploymentStatus.ARCHIVED,
        )
        .select_related('role', 'restaurant_profile', 'employee_profile')
        .first()
    )
    if user is None or not user.can_access_pos_ui:
        return None

    # Both records are updated by the archive action. A later profile edit
    # cannot widen the admission window past the user's original cutoff.
    archived_at = min(user.updated_at, user.employee_profile.updated_at)
    if not user.created_at <= occurred_at < archived_at:
        return None

    operation_id = str(operation.get('operationId') or operation.get('operation_id') or '')
    inbox = LocalAgentMutationInbox.objects.filter(
        restaurant=agent.restaurant,
        operation_id=operation_id,
        payload_hash=_hash(operation),
    ).first()
    if inbox is None:
        return None
    if inbox.created_at < archived_at:
        return user

    # Newly uploaded legacy envelopes have no durable ownership sequence, so
    # only previously received legacy evidence qualifies. Sequenced events
    # must belong to an epoch/device already observed before the archive.
    metadata = financial_event_metadata(operation)
    if metadata['eventVersion'] != 2:
        return user if _belongs_to_proven_historical_order(
            agent=agent, operation=operation, user_id=user_id,
            device_id=device_id, occurred_at=occurred_at,
        ) else None
    if not metadata['ownerEpoch'] or not metadata['sequence']:
        return None
    prior = LocalAgentMutationInbox.objects.filter(
        restaurant=agent.restaurant,
        event_version=2,
        owner_epoch=metadata['ownerEpoch'],
        created_at__lt=archived_at,
    ).filter(
        Q(operation__user_id=user_id, operation__device_id=device_id)
        | Q(operation__userId=user_id, operation__deviceId=device_id)
    ).exclude(operation_id=operation_id).exists()
    return user if prior else None
