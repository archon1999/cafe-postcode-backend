"""Preserve an archived cashier's already recorded offline work.

This only affects trusted Local Agent projection. It never changes the user's
stored active flag or permits PIN/JWT login after archival.
"""

from django.db.models import Q

from apps.local_agents.models import LocalAgentMutationInbox
from apps.local_agents.mutation_inbox import _hash, financial_event_metadata
from apps.users.models import User
from apps.users.models.employee_profile import EmployeeProfile


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
    if (metadata['eventVersion'] != 2 or not metadata['ownerEpoch']
            or not metadata['sequence']):
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
