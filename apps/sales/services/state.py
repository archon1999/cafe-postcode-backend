import logging
import re

from django.db import transaction
from django.db.models import Q
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
        from apps.kitchen.services import sync_order_tickets

        self.ensure_order_mutable(order=order)
        self.ensure_delivery_details(order=order)
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
            sync_table_status(session.table)

        logger.info(
            'Order closed after successful payment',
            extra={'order_id': str(order.pk), 'cashier_id': str(received_by.pk) if received_by else None},
        )
        return order
