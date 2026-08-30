from rest_framework import serializers

from apps.floor.models import TableSession
from apps.floor.services import session_physical_tables
from apps.kitchen.models import KitchenTicket
from apps.sales.helpers import get_order_model

Order = get_order_model()


ACTIVE_ORDER_STATUSES = {
    Order.Status.OPEN,
    Order.Status.SUBMITTED,
    Order.Status.READY,
}
PREFETCHED_ACTIVE_ORDERS_ATTR = 'serialized_active_orders'
PREFETCHED_SERVICE_TICKETS_ATTR = 'serialized_service_tickets'
_MISSING = object()


def _get_prefetched_related(instance, relation_name, *, to_attr=None):
    if to_attr:
        related = getattr(instance, to_attr, _MISSING)
        if related is not _MISSING:
            return related
    return getattr(instance, '_prefetched_objects_cache', {}).get(relation_name)


def resolve_service_state(session: TableSession) -> str:
    if session.status == TableSession.Status.PENDING_PAYMENT:
        return 'pending_payment'

    prefetched_orders = _get_prefetched_related(
        session,
        'orders',
        to_attr=PREFETCHED_ACTIVE_ORDERS_ATTR,
    )
    if prefetched_orders is None:
        active_orders = session.orders.filter(status__in=ACTIVE_ORDER_STATUSES).order_by('-created_at')
        latest_order = active_orders.first()
    else:
        active_orders = [order for order in prefetched_orders if order.status in ACTIVE_ORDER_STATUSES]
        latest_order = max(active_orders, key=lambda order: order.created_at, default=None)

    if latest_order is None:
        return 'done'

    prefetched_tickets = _get_prefetched_related(
        latest_order,
        'kitchen_tickets',
        to_attr=PREFETCHED_SERVICE_TICKETS_ATTR,
    )
    if prefetched_tickets is None:
        tickets = list(latest_order.kitchen_tickets.all())
    else:
        tickets = list(prefetched_tickets)

    if any(ticket.status == KitchenTicket.Status.COOKING for ticket in tickets):
        return 'cooking'

    if any(ticket.status == KitchenTicket.Status.NEW for ticket in tickets):
        return 'new'

    return 'done'


class ActiveSessionSummarySerializer(serializers.ModelSerializer):
    service_state = serializers.SerializerMethodField()
    primary_table_id = serializers.UUIDField(source='table_id', read_only=True)
    table_ids = serializers.SerializerMethodField()
    table_numbers = serializers.SerializerMethodField()

    class Meta:
        model = TableSession
        fields = (
            'id',
            'guest_count',
            'status',
            'assigned_waiter_id',
            'created_at',
            'opened_at',
            'service_state',
            'primary_table_id',
            'table_ids',
            'table_numbers',
        )

    def get_service_state(self, obj):
        return resolve_service_state(obj)

    @staticmethod
    def get_table_ids(obj):
        return [str(table.pk) for table in session_physical_tables(obj)]

    @staticmethod
    def get_table_numbers(obj):
        return [table.table_number for table in session_physical_tables(obj)]
