import logging

from django.utils import timezone

from apps.integrations.services import print_kitchen_ticket
from apps.sales.helpers import get_order_item_model, get_order_model

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

            if created and route_mode in [KitchenTicket.RouteMode.PRINTER, KitchenTicket.RouteMode.BOTH]:
                print_result = print_kitchen_ticket(ticket)
                ticket.is_printed = bool(print_result.get('ok'))
                ticket.printed_payload = print_result
                ticket.save(update_fields=['is_printed', 'printed_payload', 'updated_at'])
                logger.info(
                    'Kitchen ticket printer dispatch finished',
                    extra={'ticket_id': str(ticket.pk), 'order_id': str(order.pk), 'printed': ticket.is_printed},
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
