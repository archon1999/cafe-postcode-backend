from rest_framework import serializers

from apps.floor.models import TableSession
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order


ACTIVE_ORDER_STATUSES = {
    Order.Status.OPEN,
    Order.Status.SUBMITTED,
    Order.Status.READY,
}


def _get_prefetched_related(instance, relation_name):
    return getattr(instance, '_prefetched_objects_cache', {}).get(relation_name)


def resolve_service_state(session: TableSession) -> str:
    if session.status == TableSession.Status.PENDING_PAYMENT:
        return 'pending_payment'

    prefetched_orders = _get_prefetched_related(session, 'orders')
    if prefetched_orders is None:
        active_orders = session.orders.filter(status__in=ACTIVE_ORDER_STATUSES).order_by('-created_at')
        latest_order = active_orders.first()
    else:
        active_orders = [order for order in prefetched_orders if order.status in ACTIVE_ORDER_STATUSES]
        latest_order = max(active_orders, key=lambda order: order.created_at, default=None)

    if latest_order is None:
        return 'done'

    prefetched_tickets = _get_prefetched_related(latest_order, 'kitchen_tickets')
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

    class Meta:
        model = TableSession
        fields = ('id', 'guest_count', 'status', 'assigned_waiter_id', 'created_at', 'service_state')

    def get_service_state(self, obj):
        return resolve_service_state(obj)
