from apps.billing.models import CashShift


def resolve_trusted_edge_payment_shift(
    *, restaurant, edge_cash_shift_id, occurred_at
):
    """Resolve a stale edge shift only for payments made after it was closed.

    A Local Agent can briefly keep accepting payments against its cached shift
    after another terminal closes that shift on the backend.  In that narrow
    case, bind the payment to the single successor shift on the same cash desk.
    Operations without a trustworthy timestamp, or operations that happened
    before the close, deliberately remain attached to the original shift and
    fail normal validation instead of being moved across reports.
    """
    origin_shift = (
        CashShift.objects.select_related("cash_desk")
        .filter(
            pk=edge_cash_shift_id,
            cash_desk__restaurant=restaurant,
        )
        .first()
    )
    if origin_shift is None or origin_shift.status == CashShift.Status.OPEN:
        return origin_shift
    if (
        occurred_at is None
        or origin_shift.closed_at is None
        or occurred_at < origin_shift.closed_at
    ):
        return origin_shift

    successor_shifts = list(
        CashShift.objects.select_related("cash_desk")
        .filter(
            cash_desk_id=origin_shift.cash_desk_id,
            status=CashShift.Status.OPEN,
        )
        .order_by("opened_at")[:2]
    )
    if len(successor_shifts) != 1:
        return origin_shift
    return successor_shifts[0]


def can_recover_trusted_edge_payment(
    *, restaurant, edge_cash_shift_id, occurred_at
):
    shift = resolve_trusted_edge_payment_shift(
        restaurant=restaurant,
        edge_cash_shift_id=edge_cash_shift_id,
        occurred_at=occurred_at,
    )
    return bool(shift and str(shift.id) != str(edge_cash_shift_id))
