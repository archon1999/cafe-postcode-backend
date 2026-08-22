from rest_framework import status

from apps.sales.models import Order
from apps.sales.services import OrderStateService
from apps.sales.tests.support.pos_api import PosAPITestCase


class BackendOrderScenarioTests(PosAPITestCase):
    def test_counter_order_lifecycle_preserves_state_and_totals(self):
        created = self.create_order_via_api(
            {
                'distribution_point': str(self.takeaway_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        order = Order.objects.get(pk=created['id'])
        self.assertEqual(
            (order.status, order.subtotal, order.total, order.table_session_id),
            (Order.Status.OPEN, 0, 0, None),
        )

        item = self.add_item_via_api(order.id, quantity=2)
        order.refresh_from_db()
        self.assertEqual((order.subtotal, order.total), (60000, 60000))

        quantity_response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item['id']}/",
            {'quantity': 3},
            format='json',
        )
        self.assertEqual(quantity_response.status_code, status.HTTP_200_OK, quantity_response.data)
        order.refresh_from_db()
        self.assertEqual((order.subtotal, order.total), (90000, 90000))

        submitted = self.submit_order_via_api(order.id)
        self.assertEqual(submitted['status'], Order.Status.SUBMITTED)

        OrderStateService().close_order_after_payment(order=order, received_by=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(order.cashier_id, self.user.id)
        self.assertIsNotNone(order.closed_at)
        self.assertEqual((order.subtotal, order.total), (90000, 90000))

    def test_supported_counter_channels_remain_distinct(self):
        scenarios = (
            (
                Order.Channel.HALL,
                {
                    'distribution_point': str(self.hall_distribution.id),
                    'channel': Order.Channel.HALL,
                    'guest_count': 1,
                    'note': '',
                },
            ),
            (
                Order.Channel.TAKEAWAY,
                {
                    'distribution_point': str(self.takeaway_distribution.id),
                    'channel': Order.Channel.TAKEAWAY,
                    'guest_count': 1,
                    'note': '',
                },
            ),
            (
                Order.Channel.DELIVERY,
                {
                    'channel': Order.Channel.DELIVERY,
                    'guest_count': 1,
                    'note': '',
                    'delivery_phone': '90-123-45-67',
                    'delivery_address': 'Chilonzor 12',
                },
            ),
        )

        for expected_channel, payload in scenarios:
            with self.subTest(channel=expected_channel):
                created = self.create_order_via_api(payload)
                order = Order.objects.select_related('distribution_point').get(pk=created['id'])
                self.assertEqual(order.channel, expected_channel)
                self.assertEqual(order.distribution_point.kind, expected_channel)
                self.assertIsNone(order.table_session_id)

    def test_deleting_final_counter_item_removes_disposable_order(self):
        created = self.create_order_via_api(
            {
                'distribution_point': str(self.takeaway_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        item = self.add_item_via_api(created['id'], quantity=1)

        response = self.client.delete(f"/api/v1/pos/sales/orders/items/{item['id']}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['orderRemoved'])
        self.assertFalse(Order.objects.filter(pk=created['id']).exists())

    def test_table_order_and_counter_hall_share_channel_but_not_semantics(self):
        table_session = self.create_table_session(guest_count=3)
        table_order_data = self.create_order_via_api(
            {
                'table_session': str(table_session.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        table_order = Order.objects.get(pk=table_order_data['id'])
        self.assertEqual(table_order.channel, Order.Channel.HALL)
        self.assertEqual(table_order.table_session_id, table_session.id)
        self.assertEqual(table_order.guest_count, 3)

        change_response = self.client.patch(
            f'/api/v1/pos/sales/orders/{table_order.id}/',
            {'channel': Order.Channel.TAKEAWAY},
            format='json',
        )
        self.assertEqual(change_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('channel', change_response.data)

        counter_order_data = self.create_order_via_api(
            {
                'distribution_point': str(self.hall_distribution.id),
                'channel': Order.Channel.HALL,
                'guest_count': 1,
                'note': '',
            }
        )
        counter_order = Order.objects.get(pk=counter_order_data['id'])
        self.assertEqual(counter_order.channel, Order.Channel.HALL)
        self.assertIsNone(counter_order.table_session_id)
