from rest_framework import status

from apps.floor.models import DiningTable, TableSession
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class PosSmokeApiTests(PosAPITestCase):
    def test_stacked_service_fee_survives_hall_order_and_payment_flow(self):
        self.hall.service_fee_enabled = True
        self.hall.service_fee_percent = 3
        self.hall.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        self.table.service_fee_enabled = True
        self.table.service_fee_percent = 2
        self.table.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        session = self.create_table_session()

        order_data = self.create_order_via_api({'table_session': str(session.id), 'channel': Order.Channel.HALL})
        self.add_item_via_api(order_data['id'])

        order_response = self.client.get(f'/api/v1/pos/sales/orders/{order_data["id"]}/')
        self.assertEqual(order_response.status_code, status.HTTP_200_OK, order_response.data)
        self.assertEqual(order_response.data['service_fee_percent'], 15)
        self.assertEqual(order_response.data['service_fee'], 4500)
        self.assertEqual(
            [component['scope'] for component in order_response.data['service_fee_components']],
            ['restaurant', 'hall', 'table'],
        )

        self.submit_order_via_api(order_data['id'])
        payment_data = self.pay_order_via_api(order_data['id'], amount=34500)

        self.assertEqual(payment_data['order']['service_fee'], 4500)
        self.assertEqual(payment_data['order']['service_fee_percent'], 15)
        self.assertEqual(
            [component['amount'] for component in payment_data['order']['service_fee_components']],
            [3000, 900, 600],
        )

    def test_hall_order_lifecycle_smoke(self):
        session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=self.table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=4,
            status=TableSession.Status.OPEN,
        )
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])

        order_data = self.create_order_via_api(
            {
                'table_session': str(session.id),
                'channel': Order.Channel.HALL,
                'guest_count': 4,
                'note': '',
            }
        )
        order_id = order_data['id']
        item_data = self.add_item_via_api(order_id, quantity=1)

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.subtotal, 30000)
        self.assertEqual(order.total, 33000)

        submitted = self.submit_order_via_api(order_id)
        self.assertEqual(submitted['status'], Order.Status.SUBMITTED)

        ticket = KitchenTicket.objects.get(order_id=order_id, prep_station=self.prep_station)
        self.assertEqual(ticket.status, KitchenTicket.Status.NEW)

        item_status_response = self.client.post(
            f'/api/v1/pos/kitchen/items/{item_data["id"]}/status/',
            {'status': 'done'},
            format='json',
        )
        self.assertEqual(
            item_status_response.status_code,
            status.HTTP_200_OK,
            item_status_response.data,
        )

        order.refresh_from_db()
        ticket.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()

        self.assertEqual(order.status, Order.Status.READY)
        self.assertEqual(ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(session.status, TableSession.Status.OPEN)
        self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)

        open_checks_response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')
        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id) and item['service_fee_enabled'] and item['service_fee_percent'] == 10
                for item in open_checks_response.data
            )
        )

        payment_data = self.pay_order_via_api(order_id, amount=33000)
        self.assertEqual(payment_data['order']['service_fee'], 3000)
        self.assertTrue(payment_data['order']['service_fee_enabled'])
        self.assertEqual(payment_data['order']['service_fee_percent'], 10)

        order.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)

        closed_checks_response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')
        self.assertEqual(closed_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['service_fee'] == 3000
                and item['service_fee_percent'] == 10
                and item['receipts']
                for item in closed_checks_response.data['data']
            )
        )

    def test_takeaway_order_lifecycle_smoke(self):
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
        order_data = self.create_order_via_api(
            {
                'distribution_point': str(self.takeaway_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        order_id = order_data['id']
        self.add_item_via_api(order_id, quantity=2)

        order = Order.objects.get(pk=order_id)
        self.assertIsNone(order.table_session_id)
        self.assertEqual(order.subtotal, 60000)
        self.assertEqual(order.total, 60000)

        submitted = self.submit_order_via_api(order_id)
        self.assertEqual(submitted['status'], Order.Status.SUBMITTED)
        self.assertEqual(len(submitted['kitchenPrintDocuments']), 1)
        self.assertEqual(
            KitchenTicket.objects.filter(order_id=order_id, prep_station=self.prep_station).count(),
            1,
        )

        open_checks_response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')
        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['channel'] == Order.Channel.TAKEAWAY
                and not item['service_fee_enabled']
                and item['service_fee'] == 0
                and item['service_fee_percent'] == 0
                for item in open_checks_response.data
            )
        )

        payment_data = self.pay_order_via_api(order_id, amount=60000)
        self.assertEqual(payment_data['order']['channel'], Order.Channel.TAKEAWAY)
        self.assertFalse(payment_data['order']['service_fee_enabled'])
        self.assertEqual(payment_data['order']['service_fee'], 0)
        self.assertEqual(payment_data['order']['service_fee_percent'], 0)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertIsNone(order.table_session_id)

        closed_checks_response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')
        self.assertEqual(closed_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['channel'] == Order.Channel.TAKEAWAY
                and item['service_fee'] == 0
                and item['receipts']
                for item in closed_checks_response.data['data']
            )
        )
