import logging

from django.utils import timezone

from apps.printing.services import create_kitchen_ticket_print_document
from apps.sales.helpers import get_order_item_model, get_order_model
from apps.catalog.utils.prep_station import resolve_order_item_prep_station

from ..models import KitchenTicket

logger = logging.getLogger(__name__)

Order = get_order_model()
OrderItem = get_order_item_model()


class OrderTicketSyncService:
    route_mode = KitchenTicket.RouteMode.DISPLAY

    @staticmethod
    def _route_mode_for_station(station):
        if getattr(station, 'printer_integration_id', None):
            return KitchenTicket.RouteMode.BOTH
        return KitchenTicket.RouteMode.DISPLAY

    def sync(self, order: Order):
        if order.status == Order.Status.OPEN:
            deleted_count, _ = KitchenTicket.objects.filter(order=order).delete()
            if deleted_count:
                logger.info('Kitchen tickets cleared for order', extra={'order_id': str(order.pk), 'deleted_count': deleted_count})
            return

        item_queryset = order.items.exclude(status=OrderItem.Status.CANCELLED).select_related('prep_station')
        for item in item_queryset.filter(prep_station__isnull=True).select_related(
            'catalog_item__category__prep_station',
            'catalog_item__prep_station',
        ):
            station = resolve_order_item_prep_station(catalog_item=item.catalog_item, restaurant=order.restaurant)
            if station is None:
                continue
            item.prep_station = station
            item.save(update_fields=['prep_station', 'updated_at'])
        item_queryset = order.items.exclude(status=OrderItem.Status.CANCELLED).select_related('prep_station')
        station_ids = {item.prep_station_id for item in item_queryset if item.prep_station_id}

        deleted_count, _ = KitchenTicket.objects.filter(order=order).exclude(prep_station_id__in=station_ids).delete()
        if deleted_count:
            logger.info(
                'Stale kitchen tickets removed',
                extra={'order_id': str(order.pk), 'deleted_count': deleted_count},
            )

        for station_id in station_ids:
            station_items = item_queryset.filter(prep_station_id=station_id)
            station = station_items[0].prep_station
            route_mode = self._route_mode_for_station(station)
            if station_items.filter(status=OrderItem.Status.COOKING).exists():
                ticket_status = KitchenTicket.Status.COOKING
            elif station_items.exists() and not station_items.exclude(status=OrderItem.Status.DONE).exists():
                ticket_status = KitchenTicket.Status.DONE
            else:
                ticket_status = KitchenTicket.Status.NEW

            ticket, created = KitchenTicket.objects.get_or_create(
                order=order,
                prep_station_id=station_id,
                defaults={
                    'restaurant': order.restaurant,
                    'status': ticket_status,
                    'routed_via': route_mode,
                },
            )
            updates = []
            if not created and ticket.status != ticket_status:
                ticket.status = ticket_status
                updates.append('status')
            if ticket.routed_via != route_mode:
                ticket.routed_via = route_mode
                updates.append('routed_via')
            if ticket_status == KitchenTicket.Status.DONE and not ticket.completed_at:
                ticket.completed_at = timezone.now()
                updates.append('completed_at')
            if ticket_status != KitchenTicket.Status.DONE and ticket.completed_at is not None:
                ticket.completed_at = None
                updates.append('completed_at')
            if updates:
                ticket.save(update_fields=[*updates, 'updated_at'])
                logger.info(
                    'Kitchen ticket synced',
                    extra={'ticket_id': str(ticket.pk), 'order_id': str(order.pk), 'status': ticket.status},
                )

            document, _snapshot = create_kitchen_ticket_print_document(
                ticket=ticket,
                created_by=order.opened_by,
            )
            if ticket.print_document_id != document.id:
                ticket.print_document = document
                ticket.printed_payload = {
                    'status': 'queued' if route_mode in [KitchenTicket.RouteMode.PRINTER, KitchenTicket.RouteMode.BOTH] else 'display_only',
                    'print_document_id': str(document.id),
                }
                ticket.save(update_fields=['print_document', 'printed_payload', 'updated_at'])
                logger.info(
                    'Kitchen ticket print document created',
                    extra={'ticket_id': str(ticket.pk), 'order_id': str(order.pk), 'print_document_id': str(document.id)},
                )

        active_items = order.items.exclude(status=OrderItem.Status.CANCELLED)
        if active_items.exists():
            if not active_items.exclude(status=OrderItem.Status.DONE).exists() and order.status != Order.Status.CLOSED:
                order.status = Order.Status.READY
                order.save(update_fields=['status', 'updated_at'])
                logger.info('Order moved to ready state', extra={'order_id': str(order.pk)})
            elif order.status == Order.Status.READY and active_items.exclude(status=OrderItem.Status.DONE).exists():
                order.status = Order.Status.SUBMITTED
                order.save(update_fields=['status', 'updated_at'])
                logger.info('Order moved back to submitted state', extra={'order_id': str(order.pk)})
