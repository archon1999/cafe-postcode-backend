from apps.kitchen.models import KitchenTicket, KitchenTicketLine
from apps.kitchen.services import OrderTicketSyncService
from apps.kitchen.services.kitchen_status import KitchenStatusService
from apps.integrations.models import IntegrationConfig
from apps.printing.services import create_kitchen_ticket_print_document
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase, PosTestCase


class OrderTicketSyncServiceTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.service = OrderTicketSyncService()
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=1,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.SUBMITTED,
            guest_count=1,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
            status=OrderItem.Status.NEW,
        )
        self.order.recalculate_totals()

    def test_dispatch_creates_ticket_for_active_station_items(self):
        self.service.dispatch(order=self.order)

        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        self.assertEqual(ticket.status, KitchenTicket.Status.NEW)
        self.assertIsNotNone(ticket.print_document_id)
        self.assertEqual(ticket.print_document.kind, 'kitchen_ticket')

    def test_dispatch_uses_category_prep_station_for_items_without_product_station(self):
        self.category.prep_station = self.prep_station
        self.category.save(update_fields=['prep_station', 'updated_at'])
        self.catalog_item.prep_station = None
        self.catalog_item.save(update_fields=['prep_station', 'updated_at'])
        self.order_item.prep_station = None
        self.order_item.save(update_fields=['prep_station', 'updated_at'])

        self.service.dispatch(order=self.order)

        self.order_item.refresh_from_db()
        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        self.assertEqual(self.order_item.prep_station, self.prep_station)
        self.assertEqual(ticket.status, KitchenTicket.Status.NEW)

    def test_sync_marks_order_ready_when_all_active_items_done(self):
        self.service.dispatch(order=self.order)
        self.order_item.status = OrderItem.Status.DONE
        self.order_item.save(update_fields=['status', 'updated_at'])

        self.service.sync(order=self.order)

        self.order.refresh_from_db()
        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        self.assertEqual(ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(self.order.status, Order.Status.READY)

    def test_sync_keeps_auditable_ticket_when_all_station_items_cancelled(self):
        self.service.dispatch(order=self.order)
        self.order_item.status = OrderItem.Status.CANCELLED
        self.order_item.save(update_fields=['status', 'updated_at'])
        self.order.recalculate_totals()

        self.service.sync(order=self.order)

        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        self.assertEqual(ticket.status, KitchenTicket.Status.DONE)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 0)

    def test_kitchen_print_document_aggregates_duplicate_items(self):
        second_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
            status=OrderItem.Status.NEW,
        )
        self.order.recalculate_totals()
        ticket = KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=self.order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.NEW,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        KitchenTicketLine.objects.bulk_create(
            [
                KitchenTicketLine(ticket=ticket, order_item=self.order_item),
                KitchenTicketLine(ticket=ticket, order_item=second_item),
            ]
        )

        document, snapshot = create_kitchen_ticket_print_document(ticket=ticket, created_by=self.user)

        self.assertEqual(
            snapshot['items'],
            [
                {
                    'name': 'Osh',
                    'quantity': 2,
                    'unitPrice': 30000,
                    'lineTotal': 60000,
                    'note': '',
                    'modifierText': '',
                    'modifiers': [],
                }
            ],
        )
        self.assertEqual(document.kind, 'kitchen_ticket')
        self.assertEqual(document.metadata['prepStationId'], str(self.prep_station.id))

    def test_new_item_waits_for_submit_then_creates_addition_ticket_with_only_new_items(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'connection_type': 'system_printer', 'printer_name': 'Kitchen Printer'},
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=['printer_integration', 'updated_at'])
        self.service.dispatch(order=self.order)
        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        first_document_id = ticket.print_document_id

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{self.order.id}/items/',
            {'catalog_item': str(self.catalog_item.id), 'quantity': 1, 'note': ''},
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['kitchenPrintDocuments'], [])
        self.assertFalse(response.data['kitchen_dispatched'])
        self.assertEqual(KitchenTicket.objects.filter(order=self.order).count(), 1)

        submit_response = self.client.post(f'/api/v1/pos/sales/orders/{self.order.id}/submit/', {}, format='json')

        self.assertEqual(submit_response.status_code, 200, submit_response.data)
        addition = KitchenTicket.objects.get(order=self.order, dispatch_number=2)
        self.assertNotEqual(addition.print_document_id, first_document_id)
        self.assertEqual(submit_response.data['kitchenPrintDocuments'], [str(addition.print_document_id)])
        self.assertEqual(addition.lines.count(), 1)
        self.assertEqual(addition.print_document.data_snapshot['items'][0]['quantity'], 1)
        self.assertTrue(addition.print_document.data_snapshot['kitchen']['isAddition'])

        retry_response = self.client.post(f'/api/v1/pos/sales/orders/{self.order.id}/submit/', {}, format='json')
        self.assertEqual(retry_response.status_code, 200, retry_response.data)
        self.assertEqual(retry_response.data['kitchenPrintDocuments'], [])
        self.assertEqual(KitchenTicket.objects.filter(order=self.order).count(), 2)


class KitchenStatusServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.service = KitchenStatusService()
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=1,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.SUBMITTED,
            guest_count=1,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=2,
            unit_price=30000,
            status=OrderItem.Status.NEW,
        )
        self.order.recalculate_totals()
        self.ticket = KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=self.order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.NEW,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        KitchenTicketLine.objects.create(ticket=self.ticket, order_item=self.order_item)

    def test_update_item_status_cancelled_reduces_total(self):
        self.service.update_item_status(item=self.order_item, status=OrderItem.Status.CANCELLED)

        self.order.refresh_from_db()
        self.assertEqual(self.order.subtotal, 0)
        self.assertEqual(self.order.total, 0)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, KitchenTicket.Status.DONE)

    def test_update_ticket_status_done_marks_order_ready(self):
        self.service.update_ticket_status(ticket=self.ticket, status=KitchenTicket.Status.DONE)

        self.order_item.refresh_from_db()
        self.ticket.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.order_item.status, OrderItem.Status.DONE)
        self.assertEqual(self.ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(self.order.status, Order.Status.READY)
