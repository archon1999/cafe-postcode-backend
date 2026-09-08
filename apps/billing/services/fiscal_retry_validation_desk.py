from uuid import UUID

from rest_framework.exceptions import ValidationError

from apps.restaurants.models import CashDesk


def fiscal_retry_validation_desk(*, payment, payload, trusted_edge_replay):
    """Resolve evidence validation context without rewriting historical payment FKs."""
    if payment.cash_desk_id is not None:
        return payment.cash_desk
    if not trusted_edge_replay:
        raise ValidationError({'edgeCashDeskId': 'Only trusted Agent replay may supply a validation cash desk.'})
    raw_id = payload.get('edge_cash_desk_id', payload.get('edgeCashDeskId'))
    try:
        desk_id = UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError({'edgeCashDeskId': 'An explicit valid validation cash desk ID is required.'}) from error
    # No default/current desk inference: the signed original retry names this desk.
    desk = CashDesk.objects.select_related('fiscal_integration').filter(
        pk=desk_id,
        restaurant_id=payment.order.restaurant_id,
        is_active=True,
        fiscal_integration__restaurant_id=payment.order.restaurant_id,
        fiscal_integration__is_enabled=True,
        fiscal_integration__kind='fiscal',
    ).first()
    if desk is None:
        raise ValidationError({'edgeCashDeskId': 'Validation cash desk must be active and have an enabled fiscal integration in this restaurant.'})
    return desk
