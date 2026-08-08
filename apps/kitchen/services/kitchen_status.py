import logging

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.kitchen.models import KitchenTicket, KitchenTicketLine
from apps.kitchen.api.pos.serializers import KitchenTicketSerializer, OrderItemSerializer
from apps.platform.services import FeatureGateService
from apps.sales.helpers import get_order_item_model
from common.api.permissions import (
    POS_KITCHEN_ORDERS_CANCEL_PERMISSION,
    POS_KITCHEN_ORDERS_VIEW_ALL_PERMISSION,
    has_permission_code,
)

OrderItem = get_order_item_model()

logger = logging.getLogger(__name__)


class KitchenStatusService:
    feature_gate_service_class = FeatureGateService

    def _ensure_station_access(self, *, user, prep_station):
        if user is None:
            return
        if has_permission_code(user, POS_KITCHEN_ORDERS_VIEW_ALL_PERMISSION):
            return
        if not prep_station.cooks.exists():
            return
        if not prep_station.cooks.filter(pk=user.pk).exists():
            raise ValidationError({'detail': _('You do not have access to this preparation station.')})

    @staticmethod
    def _ticket_items(ticket):
        queryset = OrderItem.objects.filter(kitchen_ticket_line__ticket=ticket)
        if queryset.exists():
            return queryset
        legacy_items = ticket.order.items.filter(prep_station=ticket.prep_station)
        KitchenTicketLine.objects.bulk_create(
            [KitchenTicketLine(ticket=ticket, order_item=item) for item in legacy_items],
            ignore_conflicts=True,
        )
        return OrderItem.objects.filter(kitchen_ticket_line__ticket=ticket)

    def update_ticket_status(self, *, ticket: KitchenTicket, status: str, user=None):
        from apps.kitchen.services import sync_order_tickets

        self.feature_gate_service_class().ensure_kitchen_access(
            restaurant=ticket.order.restaurant,
            interactive=True,
        )
        self._ensure_station_access(user=user, prep_station=ticket.prep_station)

        if status not in KitchenTicket.Status.values:
            raise ValidationError({'status': _('Invalid status.')})

        item_status = {
            KitchenTicket.Status.NEW: OrderItem.Status.NEW,
            KitchenTicket.Status.COOKING: OrderItem.Status.COOKING,
            KitchenTicket.Status.DONE: OrderItem.Status.DONE,
        }[status]
        self._ticket_items(ticket).exclude(status=OrderItem.Status.CANCELLED).update(
            status=item_status,
            updated_at=timezone.now(),
        )
        ticket.status = status
        ticket.completed_at = timezone.now() if status == KitchenTicket.Status.DONE else None
        ticket.save(update_fields=['status', 'completed_at', 'updated_at'])
        sync_order_tickets(ticket.order)
        ticket.refresh_from_db()
        logger.info(
            'Kitchen ticket status updated',
            extra={'ticket_id': str(ticket.pk), 'order_id': str(ticket.order_id), 'status': status},
        )
        return KitchenTicketSerializer(ticket).data

    def update_item_status(self, *, item: OrderItem, status: str, user=None):
        from apps.kitchen.services import sync_order_tickets

        self.feature_gate_service_class().ensure_kitchen_access(
            restaurant=item.order.restaurant,
            interactive=True,
        )
        self._ensure_station_access(user=user, prep_station=item.prep_station)

        if status not in {
            OrderItem.Status.NEW,
            OrderItem.Status.COOKING,
            OrderItem.Status.DONE,
            OrderItem.Status.CANCELLED,
        }:
            raise ValidationError({'status': _('Invalid status.')})
        if (
            user is not None
            and status == OrderItem.Status.CANCELLED
            and not has_permission_code(user, POS_KITCHEN_ORDERS_CANCEL_PERMISSION)
        ):
            raise ValidationError({'status': _('Only head chef can cancel kitchen order items.')})

        item.status = status
        item.save(update_fields=['status', 'updated_at'])
        item.order.recalculate_totals()
        sync_order_tickets(item.order)
        item.refresh_from_db()
        logger.info(
            'Kitchen item status updated',
            extra={'order_item_id': str(item.pk), 'order_id': str(item.order_id), 'status': status},
        )
        return OrderItemSerializer(item).data
