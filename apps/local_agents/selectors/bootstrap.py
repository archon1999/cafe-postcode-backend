from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.kitchen.constants import KITCHEN_MONITOR_RECENTLY_DONE_WINDOW
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order


def bootstrap_kitchen_tickets(*, restaurant):
    now = timezone.now()
    cutoff = now - timedelta(days=1)
    recent_done_cutoff = now - KITCHEN_MONITOR_RECENTLY_DONE_WINDOW
    active_order_statuses = [Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY]
    return (
        KitchenTicket.objects.filter(restaurant=restaurant)
        .filter(
            Q(status__in=[KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING])
            & (Q(order__status__in=active_order_statuses) | Q(created_at__gte=cutoff))
            | Q(status=KitchenTicket.Status.DONE, completed_at__gte=recent_done_cutoff)
        )
        .select_related(
            'prep_station',
            'order__opened_by',
            'order__table_session__hall',
            'order__table_session__table',
        )
        .prefetch_related('lines__order_item__catalog_item', 'lines__order_item__prep_station')
        .order_by('created_at')
    )
