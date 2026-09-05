from collections import defaultdict

from apps.billing.models import Receipt
from .fiscal_evidence import fiscal_amount_minor


def fully_fiscalized_order_ids(order_ids):
    """An aggregate final receipt also covers earlier partial-payment tenders.

    Count physical receipts separately: fiscal coverage is an order property,
    while every accepted payment remains its own cash/card bookkeeping row.
    """
    receipts = Receipt.objects.filter(order_id__in=set(order_ids), kind=Receipt.Kind.FISCAL).select_related('order')
    total_minor = defaultdict(int)
    expected_minor = {}
    unresolved = set()
    for receipt in receipts:
        expected_minor[receipt.order_id] = int(receipt.order.total or 0) * 100
        if receipt.status != Receipt.Status.SENT:
            unresolved.add(receipt.order_id)
            continue
        try:
            total_minor[receipt.order_id] += fiscal_amount_minor(receipt.payload or {})
        except (TypeError, ValueError, AttributeError):
            # An old receipt without amount evidence cannot establish aggregate
            # coverage of a different payment. Existing direct links still work.
            continue
    return {order_id for order_id, amount in total_minor.items()
            if amount > 0 and amount == expected_minor[order_id] and order_id not in unresolved}
