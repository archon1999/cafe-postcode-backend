from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order


def bootstrap_kitchen_tickets(*, restaurant):
    cutoff = timezone.now() - timedelta(days=1)
    active_order_statuses = [Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY]
    return (
        KitchenTicket.objects.filter(
            restaurant=restaurant,
            status__in=[KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING],
        )
        .filter(Q(order__status__in=active_order_statuses) | Q(created_at__gte=cutoff))
        .select_related(
            'prep_station',
            'order__opened_by',
            'order__table_session__hall',
            'order__table_session__table',
        )
        .prefetch_related('order__items__catalog_item', 'order__items__prep_station')
        .order_by('created_at')
    )
