from apps.billing.models import CashShift
from apps.restaurants.models import CashDesk
from rest_framework.exceptions import ValidationError
from .receipt_context import parse_payload_datetime


def resolve_trusted_edge_payment_shift(*, restaurant, edge_cash_shift_id, occurred_at):
    """Historical facts belong to their original shift, regardless of arrival time."""
    return (
        CashShift.objects.select_related("cash_desk")
        .filter(
            pk=edge_cash_shift_id,
            cash_desk__restaurant=restaurant,
        )
        .first()
    )


def can_recover_trusted_edge_payment(*, restaurant, edge_cash_shift_id, occurred_at):
    return (
        resolve_trusted_edge_payment_shift(
            restaurant=restaurant,
            edge_cash_shift_id=edge_cash_shift_id,
            occurred_at=occurred_at,
        )
        is not None
    )


def materialize_edge_shift(
    *, restaurant, shift_id, body, user, occurred_at=None, closing=False
):
    existing = resolve_trusted_edge_payment_shift(
        restaurant=restaurant, edge_cash_shift_id=shift_id, occurred_at=occurred_at
    )
    if existing is not None:
        return existing

    def value(camel, snake):
        return body.get(camel, body.get(snake))

    opened_at = parse_payload_datetime(
        value("edgeCashShiftOpenedAt", "edge_cash_shift_opened_at")
    )
    closed_at = parse_payload_datetime(
        value("edgeCashShiftClosedAt", "edge_cash_shift_closed_at")
    )
    desk_id = value("edgeCashDeskId", "edge_cash_desk_id") or value(
        "cashDeskId", "cash_desk_id"
    )
    desk = (
        CashDesk.objects.filter(pk=desk_id, restaurant=restaurant).first()
        if desk_id
        else None
    )
    if not opened_at or desk is None:
        raise ValidationError(
            {
                "code": "EDGE_CASH_SHIFT_NOT_FOUND",
                "detail": "Original shift snapshot or shift-open dependency is required.",
            }
        )
    if closed_at and closed_at < opened_at:
        raise ValidationError(
            {
                "code": "INVALID_SHIFT_TIMELINE",
                "detail": "Shift close precedes its opening.",
            }
        )
    # Historical materialization must not replace or become the current live shift.
    return CashShift.objects.create(
        id=shift_id,
        cash_desk=desk,
        opened_by=user,
        opened_at=opened_at,
        status=CashShift.Status.RECONCILING,
        closed_at=closed_at if closing else None,
        reconciliation_payload={"materializedFromEvidence": True},
    )
