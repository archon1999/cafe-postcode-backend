from unittest.mock import patch

from apps.catalog.models import CatalogItem
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.sales.models import OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase


class KitchenDispatchFullFlowTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
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
        self.tea = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Choy',
            prep_station=self.prep_station,
            price=8000,
        )
        self.session = self.create_table_session(guest_count=2)
        self.order = self.create_order_via_api(
            {'table_session': str(self.session.id), 'channel': 'hall', 'note': ''}
        )

    def _enqueue_print_document(self, document_id, operation_id):
        with patch(
            'apps.printing.api.pos.views.LocalAgentCommandService.enqueue',
            return_value={'commandId': f'command-{operation_id}'},
        ) as enqueue:
            response = self.client.post(
                '/api/v1/pos/printing/jobs/',
                {
                    'operation_id': operation_id,
                    'document_id': document_id,
                    'copies': 1,
                },
                format='json',
            )
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data['job']['status'], 'queued')
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs['command_type'], 'print.document')
        self.assertEqual(enqueue.call_args.kwargs['payload']['documentId'], document_id)
        return response

    def test_initial_and_addition_dispatch_print_only_their_own_items_and_can_be_served(self):
        first_item = self.add_item_via_api(self.order['id'])
        first_submit = self.submit_order_via_api(self.order['id'])

        self.assertEqual(len(first_submit['kitchenPrintDocuments']), 1)
        first_ticket = KitchenTicket.objects.get(order_id=self.order['id'], dispatch_number=1)
        first_document_id = str(first_ticket.print_document_id)
        self.assertEqual(first_submit['kitchenPrintDocuments'], [first_document_id])
        self.assertEqual([row['name'] for row in first_ticket.print_document.data_snapshot['items']], ['Osh'])
        self._enqueue_print_document(first_document_id, 'auto:first-kitchen')

        ready_response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{first_ticket.id}/status/',
            {'status': 'done'},
            format='json',
        )
        self.assertEqual(ready_response.status_code, 200, ready_response.data)
        served_response = self.client.post(
            f"/api/v1/pos/sales/orders/{self.order['id']}/serve-ready/",
            {},
            format='json',
        )
        self.assertEqual(served_response.status_code, 200, served_response.data)
        first_ticket.refresh_from_db()
        first_order_item = OrderItem.objects.get(pk=first_item['id'])
        self.assertEqual(first_order_item.status, OrderItem.Status.SERVED)
        self.assertIsNotNone(first_ticket.handed_off_at)

        addition_item = self.add_item_via_api(self.order['id'], catalog_item=self.tea)
        self.assertEqual(addition_item['kitchenPrintDocuments'], [])
        self.assertFalse(addition_item['kitchen_dispatched'])
        self.assertEqual(KitchenTicket.objects.filter(order_id=self.order['id']).count(), 1)
        first_ticket.refresh_from_db()
        self.assertEqual([row['name'] for row in first_ticket.print_document.data_snapshot['items']], ['Osh'])

        second_submit = self.submit_order_via_api(self.order['id'])

        self.assertEqual(len(second_submit['kitchenPrintDocuments']), 1)
        addition_ticket = KitchenTicket.objects.get(order_id=self.order['id'], dispatch_number=2)
        addition_document_id = str(addition_ticket.print_document_id)
        self.assertEqual(second_submit['kitchenPrintDocuments'], [addition_document_id])
        self.assertEqual(
            [str(value) for value in addition_ticket.lines.values_list('order_item_id', flat=True)],
            [addition_item['id']],
        )
        self.assertEqual([row['name'] for row in addition_ticket.print_document.data_snapshot['items']], ['Choy'])
        self.assertTrue(addition_ticket.print_document.data_snapshot['kitchen']['isAddition'])
        self._enqueue_print_document(addition_document_id, 'auto:addition-kitchen')

        queue_response = self.client.get('/api/v1/pos/kitchen/queue/')
        self.assertEqual(queue_response.status_code, 200, queue_response.data)
        addition_row = next(
            row for row in queue_response.data['data'] if str(row['id']) == str(addition_ticket.id)
        )
        self.assertTrue(addition_row['is_addition'])
        self.assertEqual([row['catalog_item_name'] for row in addition_row['items']], ['Choy'])

        retry_submit = self.submit_order_via_api(self.order['id'])
        self.assertEqual(retry_submit['kitchenPrintDocuments'], [])
        self.assertEqual(KitchenTicket.objects.filter(order_id=self.order['id']).count(), 2)

        second_ready = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{addition_ticket.id}/status/',
            {'status': 'done'},
            format='json',
        )
        self.assertEqual(second_ready.status_code, 200, second_ready.data)
        second_served = self.client.post(
            f"/api/v1/pos/sales/orders/{self.order['id']}/serve-ready/",
            {},
            format='json',
        )
        self.assertEqual(second_served.status_code, 200, second_served.data)
        self.assertEqual(OrderItem.objects.get(pk=addition_item['id']).status, OrderItem.Status.SERVED)
