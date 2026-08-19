from rest_framework import status

from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket, KitchenTicketLine
from apps.printing.models import PrintDocument
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase


class OrderItemDeletePrintingApiTests(PosAPITestCase):
    def create_order_with_item(self, *, quantity=1):
        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        item_data = self.add_item_via_api(order_data['id'], quantity=quantity)
        return Order.objects.get(pk=order_data['id']), OrderItem.objects.get(pk=item_data['id'])

    def enable_kitchen_printer(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'Kitchen Printer',
            },
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=['printer_integration', 'updated_at'])

    def test_dispatched_printer_item_is_cancelled_and_returns_negative_document(self):
        self.enable_kitchen_printer()
        order, order_item = self.create_order_with_item()
        self.submit_order_via_api(order.id)
        original_line = KitchenTicketLine.objects.select_related('ticket').get(
            order_item=order_item,
        )

        response = self.client.delete(
            f'/api/v1/pos/sales/orders/items/{order_item.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['orderRemoved'])
        self.assertEqual(len(response.data['kitchenPrintDocuments']), 1)
        order_item.refresh_from_db()
        order.refresh_from_db()
        original_line.refresh_from_db()
        self.assertEqual(order_item.status, OrderItem.Status.CANCELLED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertTrue(KitchenTicketLine.objects.filter(pk=original_line.pk).exists())
        self.assertEqual(original_line.order_item_id, order_item.id)
        self.assertEqual(original_line.ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(order.subtotal, 0)
        self.assertEqual(order.calculated_total, 0)
        self.assertEqual(order.total, 0)

        document = PrintDocument.objects.get(
            pk=response.data['kitchenPrintDocuments'][0]
        )
        self.assertEqual(document.operation_type, PrintDocument.OperationType.REFUND)
        self.assertEqual(document.source_model, 'sales.orderitem')
        self.assertEqual(document.source_id, order_item.id)
        self.assertEqual(document.metadata['originalKitchenTicketId'], str(original_line.ticket_id))
        self.assertEqual(document.metadata['quantityDelta'], -1)
        self.assertEqual(document.data_snapshot['items'][0]['quantity'], -1)
        self.assertTrue(document.data_snapshot['items'][0]['isCancellation'])

    def test_dispatched_multi_quantity_item_prints_full_negative_quantity_and_total(self):
        self.enable_kitchen_printer()
        order, order_item = self.create_order_with_item(quantity=3)
        self.submit_order_via_api(order.id)

        response = self.client.delete(
            f'/api/v1/pos/sales/orders/items/{order_item.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        document = PrintDocument.objects.get(
            pk=response.data['kitchenPrintDocuments'][0]
        )
        self.assertEqual(document.metadata['quantityDelta'], -3)
        self.assertEqual(document.data_snapshot['items'][0]['quantity'], -3)
        self.assertEqual(document.data_snapshot['items'][0]['lineTotal'], -90000)
        self.assertEqual(document.data_snapshot['items'][0]['quantityDelta'], -3)
        self.assertEqual(document.data_snapshot['kitchen']['quantityDelta'], -3)

    def test_draft_item_is_deleted_without_a_cancellation_document(self):
        shift = self.create_cash_shift()
        order, order_item = self.create_order_with_item()

        response = self.client.delete(
            f'/api/v1/pos/sales/orders/items/{order_item.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['orderRemoved'])
        self.assertEqual(response.data['kitchenPrintDocuments'], [])
        self.assertFalse(OrderItem.objects.filter(pk=order_item.pk).exists())
        self.assertFalse(
            PrintDocument.objects.filter(
                source_model='sales.orderitem',
                source_id=order_item.id,
            ).exists()
        )
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())
        self.restaurant.refresh_from_db()
        shift.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, 0)
        self.assertEqual(shift.next_order_number, 0)

        replacement, _replacement_item = self.create_order_with_item()
        shift.refresh_from_db()
        self.assertEqual(replacement.order_number, order.order_number)
        self.assertEqual(replacement.display_name, order.display_name)
        self.assertEqual(shift.next_order_number, 1)

    def test_display_only_dispatched_item_is_cancelled_without_a_print_document(self):
        order, order_item = self.create_order_with_item()
        self.submit_order_via_api(order.id)
        ticket = KitchenTicket.objects.get(order=order)
        self.assertEqual(ticket.routed_via, KitchenTicket.RouteMode.DISPLAY)

        response = self.client.delete(
            f'/api/v1/pos/sales/orders/items/{order_item.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['orderRemoved'])
        self.assertEqual(response.data['kitchenPrintDocuments'], [])
        order_item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order_item.status, OrderItem.Status.CANCELLED)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertTrue(KitchenTicketLine.objects.filter(order_item=order_item).exists())
        open_checks = self.client.get('/api/v1/pos/billing/open-checks/')
        self.assertEqual(open_checks.status_code, status.HTTP_200_OK, open_checks.data)
        self.assertNotIn(str(order.id), {str(row['id']) for row in open_checks.data})
        self.assertFalse(
            PrintDocument.objects.filter(
                source_model='sales.orderitem',
                source_id=order_item.id,
            ).exists()
        )
