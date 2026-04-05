import logging

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.floor.models import DiningTable, TableSession
from apps.restaurants.helpers import get_restaurant_model
from apps.sales.helpers import get_order_model

logger = logging.getLogger(__name__)

Order = get_order_model()
Restaurant = get_restaurant_model()


class OrderStateService:
    MUTABLE_ORDER_STATUSES = frozenset({Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY})

    @transaction.atomic
    def next_order_number(self, *, restaurant: Restaurant | None = None, branch: Restaurant | None = None) -> int:
        restaurant = restaurant or branch
        if restaurant is None:
            raise ValueError('restaurant is required')
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        locked_restaurant.last_order_number += 1
        locked_restaurant.save(update_fields=['last_order_number', 'updated_at'])
        return locked_restaurant.last_order_number

    def ensure_session_accepts_new_order(self, *, table_session):
        if table_session is None:
            return

        if table_session.status in {TableSession.Status.CLOSED, TableSession.Status.MERGED}:
            logger.warning(
                'Rejected order creation for immutable table session',
                extra={'table_session_id': str(table_session.pk), 'session_status': table_session.status},
            )
            raise ValidationError({'table_session': _('This table session is no longer active.')})

        if table_session.orders.exclude(status__in=[Order.Status.CLOSED, Order.Status.CANCELLED]).exists():
            logger.warning(
                'Rejected order creation for table session with existing active order',
                extra={'table_session_id': str(table_session.pk)},
            )
            raise ValidationError({'table_session': _('This table session already has an active order.')})

    def ensure_order_mutable(self, *, order: Order):
        if order.status in {Order.Status.CLOSED, Order.Status.CANCELLED}:
            logger.warning(
                'Rejected mutation for immutable order',
                extra={'order_id': str(order.pk), 'order_status': order.status},
            )
            raise ValidationError({'detail': _('Closed or cancelled orders cannot be modified.')})

    def ensure_order_can_be_paid(self, *, order: Order):
        if order.status == Order.Status.CANCELLED:
            logger.warning('Rejected payment for cancelled order', extra={'order_id': str(order.pk)})
            raise ValidationError({'detail': _('Cancelled orders cannot be paid.')})
        if order.status == Order.Status.CLOSED:
            logger.warning('Rejected payment for closed order', extra={'order_id': str(order.pk)})
            raise ValidationError({'detail': _('Closed orders cannot be paid again.')})

    def submit_order(self, *, order: Order):
        from apps.kitchen.services import sync_order_tickets

        self.ensure_order_mutable(order=order)
        if order.status == Order.Status.OPEN:
            order.status = Order.Status.SUBMITTED
            order.save(update_fields=['status', 'updated_at'])

        sync_order_tickets(order)
        return order

    def sync_after_items_changed(self, *, order: Order):
        from apps.kitchen.services import sync_order_tickets

        self.ensure_order_mutable(order=order)
        order.recalculate_totals()
        if order.status != Order.Status.OPEN:
            sync_order_tickets(order)
        return order

    def close_order_after_payment(self, *, order: Order, received_by):
        now = timezone.now()
        order.status = Order.Status.CLOSED
        order.cashier = received_by
        order.closed_at = now
        order.save(update_fields=['status', 'cashier', 'closed_at', 'updated_at'])

        if order.table_session_id:
            session = order.table_session
            session.status = TableSession.Status.CLOSED
            session.closed_at = now
            session.save(update_fields=['status', 'closed_at', 'updated_at'])
            session.table.status = DiningTable.Status.AVAILABLE
            session.table.save(update_fields=['status', 'updated_at'])

        logger.info(
            'Order closed after successful payment',
            extra={'order_id': str(order.pk), 'cashier_id': str(received_by.pk) if received_by else None},
        )
        return order
