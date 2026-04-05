import logging

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.kitchen.models import KitchenTicket
from apps.kitchen.serializers import KitchenTicketSerializer, OrderItemSerializer
from apps.platform.services import FeatureGateService
from apps.sales.helpers import get_order_item_model

OrderItem = get_order_item_model()

logger = logging.getLogger(__name__)


class KitchenStatusService:
    feature_gate_service_class = FeatureGateService

    def update_ticket_status(self, *, ticket: KitchenTicket, status: str):
        from apps.kitchen.services import sync_order_tickets

        self.feature_gate_service_class().ensure_kitchen_access(
            restaurant=ticket.order.restaurant,
            interactive=True,
        )

        if status not in KitchenTicket.Status.values:
            raise ValidationError({'status': _('Invalid status.')})

        item_status = {
            KitchenTicket.Status.NEW: OrderItem.Status.NEW,
            KitchenTicket.Status.COOKING: OrderItem.Status.COOKING,
            KitchenTicket.Status.DONE: OrderItem.Status.DONE,
        }[status]
        ticket.order.items.filter(prep_station=ticket.prep_station).exclude(status=OrderItem.Status.CANCELLED).update(
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

    def update_item_status(self, *, item: OrderItem, status: str):
        from apps.kitchen.services import sync_order_tickets

        self.feature_gate_service_class().ensure_kitchen_access(
            restaurant=item.order.restaurant,
            interactive=True,
        )

        if status not in {
            OrderItem.Status.NEW,
            OrderItem.Status.COOKING,
            OrderItem.Status.DONE,
            OrderItem.Status.CANCELLED,
        }:
            raise ValidationError({'status': _('Invalid status.')})

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
