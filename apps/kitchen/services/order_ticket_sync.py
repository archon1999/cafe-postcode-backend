import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.catalog.utils.prep_station import resolve_order_item_prep_station
from apps.printing.services import create_kitchen_ticket_print_document
from apps.sales.helpers import get_order_item_model, get_order_model

from ..models import KitchenTicket, KitchenTicketLine

logger = logging.getLogger(__name__)

Order = get_order_model()
OrderItem = get_order_item_model()


class OrderTicketSyncService:
    kitchen_complete_item_statuses = (OrderItem.Status.DONE, OrderItem.Status.SERVED)

    @staticmethod
    def _route_mode_for_station(station):
        if getattr(station, 'printer_integration_id', None):
            return KitchenTicket.RouteMode.BOTH
        return KitchenTicket.RouteMode.DISPLAY

    @staticmethod
    def _resolve_item_station(item, order):
        if item.prep_station_id:
            return item.prep_station
        station = resolve_order_item_prep_station(
            catalog_item=item.catalog_item,
            restaurant=order.restaurant,
        )
        if station is not None:
            item.prep_station = station
            item.save(update_fields=['prep_station', 'updated_at'])
        return station

    @transaction.atomic
    def dispatch(self, order: Order, *, created_by=None) -> list[KitchenTicket]:
        """Create one immutable kitchen batch for every unsent item in the order."""
        locked_order = (
            Order.objects.select_for_update()
            .select_related('restaurant', 'opened_by')
            .get(pk=order.pk)
        )
        pending_items = list(
            locked_order.items.exclude(status=OrderItem.Status.CANCELLED)
            .filter(kitchen_ticket_line__isnull=True)
            .select_related(
                'prep_station',
                'catalog_item__category__prep_station',
                'catalog_item__prep_station',
            )
            .prefetch_related('modifiers')
            .order_by('created_at')
        )

        items_by_station = defaultdict(list)
        for item in pending_items:
            station = self._resolve_item_station(item, locked_order)
            if station is not None:
                items_by_station[station.id].append(item)

        if not items_by_station:
            return []

        latest_dispatch = (
            KitchenTicket.objects.filter(order=locked_order).aggregate(value=Max('dispatch_number'))['value'] or 0
        )
        dispatch_number = latest_dispatch + 1
        created_tickets = []

        for station_id, station_items in items_by_station.items():
            station = station_items[0].prep_station
            route_mode = self._route_mode_for_station(station)
            ticket = KitchenTicket.objects.create(
                restaurant=locked_order.restaurant,
                order=locked_order,
                prep_station_id=station_id,
                dispatch_number=dispatch_number,
                status=KitchenTicket.Status.NEW,
                routed_via=route_mode,
            )
            KitchenTicketLine.objects.bulk_create(
                [KitchenTicketLine(ticket=ticket, order_item=item) for item in station_items]
            )
            document, _snapshot = create_kitchen_ticket_print_document(
                ticket=ticket,
                created_by=created_by or locked_order.opened_by,
            )
            ticket.print_document = document
            ticket.printed_payload = {
                'status': (
                    'queued'
                    if route_mode in (KitchenTicket.RouteMode.PRINTER, KitchenTicket.RouteMode.BOTH)
                    else 'display_only'
                ),
                'print_document_id': str(document.id),
                'dispatch_number': dispatch_number,
            }
            ticket.save(update_fields=['print_document', 'printed_payload', 'updated_at'])
            created_tickets.append(ticket)
            logger.info(
                'Kitchen dispatch ticket created',
                extra={
                    'ticket_id': str(ticket.pk),
                    'order_id': str(locked_order.pk),
                    'dispatch_number': dispatch_number,
                    'item_count': len(station_items),
                    'print_document_id': str(document.id),
                },
            )

        return created_tickets

    def _sync_ticket(self, ticket: KitchenTicket):
        items = OrderItem.objects.filter(kitchen_ticket_line__ticket=ticket).exclude(
            status=OrderItem.Status.CANCELLED,
        )
        if items.filter(status=OrderItem.Status.COOKING).exists():
            ticket_status = KitchenTicket.Status.COOKING
        elif not items.exists() or not items.exclude(status__in=self.kitchen_complete_item_statuses).exists():
            ticket_status = KitchenTicket.Status.DONE
        else:
            ticket_status = KitchenTicket.Status.NEW

        updates = []
        if ticket.status != ticket_status:
            ticket.status = ticket_status
            updates.append('status')
        if ticket_status == KitchenTicket.Status.DONE and ticket.completed_at is None:
            ticket.completed_at = timezone.now()
            updates.append('completed_at')
        if ticket_status != KitchenTicket.Status.DONE and ticket.completed_at is not None:
            ticket.completed_at = None
            updates.append('completed_at')
        route_mode = self._route_mode_for_station(ticket.prep_station)
        if ticket.routed_via != route_mode:
            ticket.routed_via = route_mode
            updates.append('routed_via')
        if updates:
            ticket.save(update_fields=[*updates, 'updated_at'])

    def _sync_order_status(self, order: Order):
        if order.status in (Order.Status.OPEN, Order.Status.CLOSED, Order.Status.CANCELLED):
            return

        routed_items = order.items.exclude(status=OrderItem.Status.CANCELLED).filter(
            kitchen_ticket_line__isnull=False,
        )
        unsent_kitchen_items = order.items.exclude(status=OrderItem.Status.CANCELLED).filter(
            prep_station__isnull=False,
            kitchen_ticket_line__isnull=True,
        )
        is_ready = (
            routed_items.exists()
            and not unsent_kitchen_items.exists()
            and not routed_items.exclude(status__in=self.kitchen_complete_item_statuses).exists()
        )

        if is_ready and order.status != Order.Status.READY:
            order.status = Order.Status.READY
            order.save(update_fields=['status', 'updated_at'])
            from apps.kitchen.services.kitchen_announcements import create_ready_announcement

            create_ready_announcement(order=order)
            logger.info('Order moved to ready state', extra={'order_id': str(order.pk)})
        elif not is_ready and order.status == Order.Status.READY:
            order.status = Order.Status.SUBMITTED
            order.save(update_fields=['status', 'updated_at'])
            logger.info('Order moved back to submitted state', extra={'order_id': str(order.pk)})

    def sync(self, order: Order):
        if order.status == Order.Status.OPEN:
            return

        tickets = KitchenTicket.objects.filter(order=order).select_related('prep_station')
        for ticket in tickets:
            self._sync_ticket(ticket)
        self._sync_order_status(order)
