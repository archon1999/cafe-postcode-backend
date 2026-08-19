import logging
import re

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.floor.models import DiningTable, TableSession
from apps.billing.helpers import get_cash_shift_model
from apps.floor.services import sync_table_status
from apps.restaurants.helpers import get_distribution_point_model, get_restaurant_model
from apps.sales.helpers import get_order_model

logger = logging.getLogger(__name__)

Order = get_order_model()
CashShift = get_cash_shift_model()
DistributionPoint = get_distribution_point_model()
Restaurant = get_restaurant_model()
DELIVERY_PHONE_RE = re.compile(r'^\d{2}-\d{3}-\d{2}-\d{2}$')


class OrderStateService:
    MUTABLE_ORDER_STATUSES = frozenset({Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY})
    DISTRIBUTION_POINT_NAMES = {
        Order.Channel.HALL: 'Zal buyurtmalari',
        Order.Channel.TAKEAWAY: 'Olib ketish',
        Order.Channel.DELIVERY: 'Yetkazib berish',
        Order.Channel.ONLINE: 'Online',
    }

    @transaction.atomic
    def next_order_number(self, *, restaurant: Restaurant | None = None, branch: Restaurant | None = None) -> int:
        restaurant = restaurant or branch
        if restaurant is None:
            raise ValueError('restaurant is required')
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        locked_restaurant.last_order_number += 1
        locked_restaurant.save(update_fields=['last_order_number', 'updated_at'])
        return locked_restaurant.last_order_number

    def next_shift_display_name(self, *, restaurant: Restaurant, user=None) -> str:
        return self.reconcile_shift_display_name(restaurant=restaurant, user=user)

    def reconcile_shift_display_name(
        self,
        *,
        restaurant: Restaurant,
        user=None,
        requested_display_name: str = '',
    ) -> str:
        queryset = CashShift.objects.select_for_update().filter(
            cash_desk__restaurant=restaurant,
            status=CashShift.Status.OPEN,
        )
        shift = None
        if user is not None:
            shift = queryset.filter(Q(cashier=user) | Q(cashier__isnull=True)).order_by('-opened_at').first()
        if shift is None:
            shift = queryset.order_by('-opened_at').first()
        if shift is None:
            return str(requested_display_name or '').strip()

        requested = str(requested_display_name or '').strip()
        requested_number = 0
        if requested.isdecimal():
            requested_number = int(requested)

        # Trusted Local Agent replays may already contain the number printed
        # while offline. Advance the backend counter to at least that value.
        # If another online writer has already consumed it, allocate the next
        # canonical number instead of persisting a duplicate.
        shift.next_order_number = max(shift.next_order_number + 1, requested_number)
        shift.save(update_fields=['next_order_number', 'updated_at'])
        return str(shift.next_order_number)

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

    @staticmethod
    def ensure_table_session_matches_restaurant(*, table_session, restaurant: Restaurant):
        if table_session is None:
            return

        session_restaurant_id = table_session.restaurant_id
        hall_restaurant_id = table_session.hall.restaurant_id
        table_hall_id = table_session.table.hall_id
        if (
            session_restaurant_id != restaurant.id
            or hall_restaurant_id != restaurant.id
            or table_hall_id != table_session.hall_id
        ):
            raise ValidationError(
                {'table_session': _('Table session does not belong to this restaurant.')}
            )

    def resolve_distribution_point(self, *, restaurant: Restaurant, channel: str, table_session=None):
        if table_session is not None:
            channel = Order.Channel.HALL

        queryset = DistributionPoint.objects.filter(
            restaurant=restaurant,
            kind=channel,
            is_active=True,
        )
        if channel == Order.Channel.HALL and table_session is not None:
            hall_point = queryset.filter(assigned_hall=table_session.hall).first()
            if hall_point is not None:
                return hall_point

        distribution_point = queryset.first()
        if distribution_point is not None:
            return distribution_point

        defaults = {
            'name': self.DISTRIBUTION_POINT_NAMES.get(channel, str(channel).title()),
            'is_active': True,
        }
        if channel == Order.Channel.HALL and table_session is not None:
            defaults['assigned_hall'] = table_session.hall
        return DistributionPoint.objects.create(
            restaurant=restaurant,
            kind=channel,
            **defaults,
        )

    def ensure_distribution_point_matches_order(self, *, distribution_point, restaurant: Restaurant, channel: str):
        if distribution_point is None:
            return

        if distribution_point.restaurant_id != restaurant.id:
            raise ValidationError({'distribution_point': _('Distribution point does not belong to this restaurant.')})
        if distribution_point.kind != channel:
            raise ValidationError({'distribution_point': _('Distribution point kind must match order channel.')})

    @staticmethod
    def ensure_catalog_item_matches_order(*, catalog_item, order: Order):
        if catalog_item is None:
            return
        if catalog_item.restaurant_id != order.restaurant_id:
            raise ValidationError(
                {'catalog_item': _('Catalog item does not belong to this restaurant.')}
            )

    @staticmethod
    @transaction.atomic
    def remove_order_item(*, order_item, one_unit: bool = False):
        from apps.kitchen.models import KitchenTicketLine

        order_item = (
            type(order_item).objects.select_for_update()
            .select_related('order')
            .get(pk=order_item.pk)
        )
        if one_unit and order_item.status == order_item.Status.CANCELLED:
            raise ValidationError({'detail': _('Cancelled order items cannot be modified.')})
        if KitchenTicketLine.objects.filter(order_item=order_item).exists():
            if one_unit and order_item.quantity > 1:
                return OrderStateService._replace_dispatched_item_remainder(
                    order_item=order_item,
                )
            order_item.status = order_item.Status.CANCELLED
            order_item.save(update_fields=['status', 'updated_at'])
            return order_item

        if one_unit and order_item.quantity > 1:
            order_item.quantity -= 1
            order_item.save(update_fields=['quantity', 'line_total', 'updated_at'])
            return order_item

        order_item.delete()
        return order_item

    @staticmethod
    def _replace_dispatched_item_remainder(*, order_item):
        from apps.sales.models import OrderItemModifier

        modifier_snapshots = list(order_item.modifiers.all())
        replacement = type(order_item).objects.create(
            order_id=order_item.order_id,
            catalog_item_id=order_item.catalog_item_id,
            prep_station_id=order_item.prep_station_id,
            created_by_id=order_item.created_by_id,
            quantity=order_item.quantity - 1,
            sale_unit=order_item.sale_unit,
            base_unit_price=order_item.base_unit_price,
            unit_price=order_item.unit_price,
            status=order_item.status,
            note=order_item.note,
        )
        OrderItemModifier.objects.bulk_create(
            [
                OrderItemModifier(
                    order_item=replacement,
                    modifier_option_id=modifier.modifier_option_id,
                    group_name=modifier.group_name,
                    option_name=modifier.option_name,
                    price_delta=modifier.price_delta,
                    sort_order=modifier.sort_order,
                )
                for modifier in modifier_snapshots
            ]
        )
        order_item.markings.update(order_item=replacement)
        order_item.status = order_item.Status.CANCELLED
        order_item.save(update_fields=['status', 'updated_at'])
        return replacement

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

    def ensure_delivery_details(self, *, order: Order):
        if order.channel != Order.Channel.DELIVERY:
            return

        phone = (order.delivery_phone or '').strip()
        address = (order.delivery_address or '').strip()
        errors = {}
        if not phone:
            errors['delivery_phone'] = _('Delivery phone is required.')
        elif not DELIVERY_PHONE_RE.match(phone):
            errors['delivery_phone'] = _('Delivery phone must match DD-DDD-DD-DD.')
        if not address:
            errors['delivery_address'] = _('Delivery address is required.')
        if errors:
            raise ValidationError(errors)

    def submit_order(self, *, order: Order):
        from apps.kitchen.services import dispatch_order_tickets, sync_order_tickets

        self.ensure_order_mutable(order=order)
        self.ensure_delivery_details(order=order)
        if order.status == Order.Status.OPEN:
            order.status = Order.Status.SUBMITTED
            order.save(update_fields=['status', 'updated_at'])

        tickets = dispatch_order_tickets(order, created_by=order.opened_by)
        sync_order_tickets(order)
        return tickets

    def sync_after_items_changed(self, *, order: Order):
        from apps.kitchen.services import sync_order_tickets

        self.ensure_order_mutable(order=order)
        order.recalculate_totals()
        if order.status != Order.Status.OPEN:
            sync_order_tickets(order)
        return order

    @transaction.atomic
    def remove_empty_order(self, *, order: Order) -> bool:
        """Remove an itemless order from active POS flows.

        Open orders are disposable builder drafts, so they are hard-deleted and
        their tail order number is released. Submitted orders keep their item
        and kitchen audit trail, but become cancelled and disappear from open
        checks.
        """
        from apps.sales.models import OrderItem

        order = (
            Order.objects.select_for_update()
            .select_related('restaurant', 'table_session__table')
            .get(pk=order.pk)
        )
        if order.items.exclude(status=OrderItem.Status.CANCELLED).exists():
            return False

        if order.status == Order.Status.OPEN and not order.payments.exists():
            locked_restaurant = Restaurant.objects.select_for_update().get(pk=order.restaurant_id)
            if locked_restaurant.last_order_number == order.order_number:
                previous_number = (
                    Order.objects.filter(restaurant_id=order.restaurant_id)
                    .exclude(pk=order.pk)
                    .aggregate(number=Max('order_number'))['number']
                    or 0
                )
                locked_restaurant.last_order_number = previous_number
                locked_restaurant.save(update_fields=['last_order_number', 'updated_at'])

            display_name = str(order.display_name or '').strip()
            if display_name.isdecimal():
                shift = (
                    CashShift.objects.select_for_update()
                    .filter(
                        cash_desk__restaurant_id=order.restaurant_id,
                        status=CashShift.Status.OPEN,
                        next_order_number=int(display_name),
                    )
                    .filter(Q(cashier_id=order.opened_by_id) | Q(cashier__isnull=True))
                    .order_by('-opened_at')
                    .first()
                )
                if shift is not None:
                    shift.next_order_number = max(shift.next_order_number - 1, 0)
                    shift.save(update_fields=['next_order_number', 'updated_at'])

            order.delete()
            return True

        order.status = Order.Status.CANCELLED
        order.closed_at = timezone.now()
        order.save(update_fields=['status', 'closed_at', 'updated_at'])
        if order.table_session_id:
            session = order.table_session
            session.status = TableSession.Status.CLOSED
            session.closed_at = order.closed_at
            session.save(update_fields=['status', 'closed_at', 'updated_at'])
            sync_table_status(session.table)
        return True

    def serve_ready_items(self, *, order: Order):
        from apps.kitchen.models import KitchenTicket
        from apps.kitchen.services import sync_order_tickets

        self.ensure_order_mutable(order=order)
        now = timezone.now()
        served_count = order.items.filter(status='done').update(status='served', updated_at=now)
        if not served_count:
            raise ValidationError({'detail': _('There are no ready items to serve.')})

        for ticket in KitchenTicket.objects.filter(order=order, status=KitchenTicket.Status.DONE):
            has_unserved_items = ticket.lines.exclude(
                order_item__status__in=['served', 'cancelled'],
            ).exists()
            if not has_unserved_items and ticket.handed_off_at is None:
                ticket.handed_off_at = now
                ticket.save(update_fields=['handed_off_at', 'updated_at'])
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
            sync_table_status(session.table)

        logger.info(
            'Order closed after successful payment',
            extra={'order_id': str(order.pk), 'cashier_id': str(received_by.pk) if received_by else None},
        )
        return order
