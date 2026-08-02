from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order, OrderItem


CLOSED_ORDER_KITCHEN_GRACE_PERIOD = timedelta(minutes=60)


@transaction.atomic
def complete_stale_closed_order_kitchen_work(*, restaurant, now=None) -> dict[str, int]:
    completed_at = now or timezone.now()
    cutoff = completed_at - CLOSED_ORDER_KITCHEN_GRACE_PERIOD
    stale_tickets = KitchenTicket.objects.select_for_update().filter(
        restaurant=restaurant,
        status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
        order__status=Order.Status.CLOSED,
        order__closed_at__isnull=False,
        order__closed_at__lte=cutoff,
    )
    ticket_rows = list(stale_tickets.values_list('id', 'order_id'))
    if not ticket_rows:
        return {'tickets': 0, 'items': 0}

    ticket_ids = [ticket_id for ticket_id, _order_id in ticket_rows]
    order_ids = list({_order_id for _ticket_id, _order_id in ticket_rows})
    updated_items = OrderItem.objects.filter(
        order_id__in=order_ids,
        status__in=(OrderItem.Status.NEW, OrderItem.Status.COOKING),
    ).update(status=OrderItem.Status.DONE, updated_at=completed_at)
    updated_tickets = KitchenTicket.objects.filter(
        id__in=ticket_ids,
        status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
    ).update(
        status=KitchenTicket.Status.DONE,
        completed_at=completed_at,
        updated_at=completed_at,
    )
    return {'tickets': updated_tickets, 'items': updated_items}
