from django.db.models import Prefetch

from apps.floor.api.admin.serializers.active_session_summary import (
    ACTIVE_ORDER_STATUSES,
    PREFETCHED_ACTIVE_ORDERS_ATTR,
    PREFETCHED_SERVICE_TICKETS_ATTR,
)
from apps.floor.api.admin.serializers.dining_table import (
    PREFETCHED_ACTIVE_ATTACHED_SESSION_LINKS_ATTR,
    PREFETCHED_ACTIVE_SESSIONS_ATTR,
)
from apps.floor.models import DiningTable, Hall, TableSession, TableSessionTable
from apps.floor.services import (
    ACTIVE_SESSION_STATUSES,
    PREFETCHED_ACTIVE_TABLE_LINKS_ATTR,
)
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order


def pos_hall_queryset(*, restaurant):
    service_tickets = KitchenTicket.objects.filter(
        status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
    )
    active_orders = (
        Order.objects.filter(status__in=ACTIVE_ORDER_STATUSES)
        .prefetch_related(
            Prefetch(
                'kitchen_tickets',
                queryset=service_tickets,
                to_attr=PREFETCHED_SERVICE_TICKETS_ATTR,
            )
        )
        .order_by('-created_at')
    )
    active_table_links = TableSessionTable.objects.filter(
        released_at__isnull=True,
    ).select_related('table')
    active_sessions = (
        TableSession.objects.filter(status__in=ACTIVE_SESSION_STATUSES)
        .prefetch_related(
            Prefetch(
                'orders',
                queryset=active_orders,
                to_attr=PREFETCHED_ACTIVE_ORDERS_ATTR,
            ),
            Prefetch(
                'attached_table_links',
                queryset=active_table_links,
                to_attr=PREFETCHED_ACTIVE_TABLE_LINKS_ATTR,
            ),
        )
        .order_by('-created_at')
    )
    attached_links = (
        TableSessionTable.objects.filter(
            released_at__isnull=True,
            session__status__in=ACTIVE_SESSION_STATUSES,
        )
        .select_related('session', 'session__table', 'session__hall')
        .prefetch_related(
            Prefetch(
                'session__orders',
                queryset=active_orders,
                to_attr=PREFETCHED_ACTIVE_ORDERS_ATTR,
            ),
            Prefetch(
                'session__attached_table_links',
                queryset=active_table_links,
                to_attr=PREFETCHED_ACTIVE_TABLE_LINKS_ATTR,
            ),
        )
    )
    tables = (
        DiningTable.objects.select_related('zone')
        .prefetch_related(
            Prefetch(
                'table_sessions',
                queryset=active_sessions,
                to_attr=PREFETCHED_ACTIVE_SESSIONS_ATTR,
            ),
            Prefetch(
                'attached_session_links',
                queryset=attached_links,
                to_attr=PREFETCHED_ACTIVE_ATTACHED_SESSION_LINKS_ATTR,
            ),
        )
        .order_by('table_number', 'name')
    )
    return (
        Hall.objects.filter(
            zone_or_cabin__restaurant=restaurant,
            is_active=True,
        )
        .select_related('zone_or_cabin', 'zone_or_cabin__restaurant')
        .prefetch_related(Prefetch('tables', queryset=tables))
        .order_by('sort_order', 'name')
    )
