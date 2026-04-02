from rest_framework import status

from apps.floor.models import DiningTable, TableSession
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order
from common.tests.pos_api import PosAPITestCase


class PosSmokeApiTests(PosAPITestCase):

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
                'distribution_point': str(self.hall_distribution.id),
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
            f"/api/v1/pos/kitchen/items/{item_data['id']}/status/",
            {'status': 'done'},
            format='json',
        )
        self.assertEqual(item_status_response.status_code, status.HTTP_200_OK, item_status_response.data)

        order.refresh_from_db()
        ticket.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()

        self.assertEqual(order.status, Order.Status.READY)
        self.assertEqual(ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(session.status, TableSession.Status.OPEN)
        self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)

        open_checks_response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')
        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(any(item['id'] == str(order_id) and item['service_fee_percent'] == 10 for item in open_checks_response.data))

        payment_data = self.pay_order_via_api(order_id, amount=33000)
        self.assertEqual(payment_data['order']['service_fee'], 3000)
        self.assertEqual(payment_data['order']['service_fee_percent'], 10)

        order.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)

        closed_checks_response = self.client.get('/api/v1/pos/payments/open-checks/?status=closed')
        self.assertEqual(closed_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['service_fee'] == 3000
                and item['service_fee_percent'] == 10
                and item['receipts']
                for item in closed_checks_response.data
            )
        )

    def test_takeaway_order_lifecycle_smoke(self):
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
        self.assertEqual(KitchenTicket.objects.filter(order_id=order_id, prep_station=self.prep_station).count(), 1)

        open_checks_response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')
        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['channel'] == Order.Channel.TAKEAWAY
                and item['service_fee'] == 0
                and item['service_fee_percent'] == 0
                for item in open_checks_response.data
            )
        )

        payment_data = self.pay_order_via_api(order_id, amount=60000)
        self.assertEqual(payment_data['order']['channel'], Order.Channel.TAKEAWAY)
        self.assertEqual(payment_data['order']['service_fee'], 0)
        self.assertEqual(payment_data['order']['service_fee_percent'], 0)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertIsNone(order.table_session_id)

        closed_checks_response = self.client.get('/api/v1/pos/payments/open-checks/?status=closed')
        self.assertEqual(closed_checks_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                item['id'] == str(order_id)
                and item['channel'] == Order.Channel.TAKEAWAY
                and item['service_fee'] == 0
                and item['receipts']
                for item in closed_checks_response.data
            )
        )
