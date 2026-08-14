from apps.sales.models import Order, OrderItem
from apps.billing.models import Payment, Receipt
from apps.floor.models import TableSession, ZoneOrCabin
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase


class OrderSerializerTests(PosTestCase):
    def create_service_fee_order(self):
        table_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=self.table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=4,
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=table_session,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            order_number=100,
            channel=Order.Channel.HALL,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        return order

    def test_combines_restaurant_hall_and_table_service_fees_as_separate_components(
        self,
    ):
        self.hall.service_fee_enabled = True
        self.hall.service_fee_percent = 3
        self.hall.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        self.table.service_fee_enabled = True
        self.table.service_fee_percent = 2
        self.table.save(update_fields=['service_fee_enabled', 'service_fee_percent'])

        data = OrderSerializer(self.create_service_fee_order()).data

        self.assertEqual(data['service_fee_percent'], 15)
        self.assertEqual(data['service_fee'], 4500)
        self.assertEqual(data['total'], 34500)
        self.assertEqual(
            data['service_fee_components'],
            [
                {
                    'scope': 'restaurant',
                    'source_name': 'Test restaurant',
                    'percent': 10,
                    'amount': 3000,
                },
                {
                    'scope': 'hall',
                    'source_name': 'Asosiy zal',
                    'percent': 3,
                    'amount': 900,
                },
                {
                    'scope': 'table',
                    'source_name': 'Asosiy zal 1',
                    'percent': 2,
                    'amount': 600,
                },
            ],
        )

    def test_applies_table_service_fee_when_restaurant_and_hall_fees_are_disabled(self):
        self.restaurant.service_fee_enabled = False
        self.restaurant.save(update_fields=['service_fee_enabled'])
        self.table.service_fee_enabled = True
        self.table.service_fee_percent = 5
        self.table.save(update_fields=['service_fee_enabled', 'service_fee_percent'])

        data = OrderSerializer(self.create_service_fee_order()).data

        self.assertEqual(data['service_fee_percent'], 5)
        self.assertEqual(data['service_fee'], 1500)
        self.assertEqual([row['scope'] for row in data['service_fee_components']], ['table'])

    def test_applies_hall_service_fee_without_restaurant_or_table_fee(self):
        self.restaurant.service_fee_enabled = False
        self.restaurant.save(update_fields=['service_fee_enabled'])
        self.hall.service_fee_enabled = True
        self.hall.service_fee_percent = 7
        self.hall.save(update_fields=['service_fee_enabled', 'service_fee_percent'])

        data = OrderSerializer(self.create_service_fee_order()).data

        self.assertEqual(data['service_fee_percent'], 7)
        self.assertEqual(data['service_fee'], 2100)
        self.assertEqual([row['scope'] for row in data['service_fee_components']], ['hall'])

    def test_service_fee_snapshot_is_stable_after_configuration_changes(self):
        self.hall.service_fee_enabled = True
        self.hall.service_fee_percent = 3
        self.hall.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        order = self.create_service_fee_order()

        self.restaurant.service_fee_percent = 20
        self.restaurant.save(update_fields=['service_fee_percent'])
        self.hall.service_fee_percent = 8
        self.hall.save(update_fields=['service_fee_percent'])
        order.recalculate_totals()
        data = OrderSerializer(order).data

        self.assertEqual(data['service_fee_percent'], 13)
        self.assertEqual(data['service_fee'], 3900)

    def test_no_service_fee_when_all_three_levels_are_disabled(self):
        self.restaurant.service_fee_enabled = False
        self.restaurant.save(update_fields=['service_fee_enabled'])

        data = OrderSerializer(self.create_service_fee_order()).data

        self.assertFalse(data['service_fee_enabled'])
        self.assertEqual(data['service_fee_percent'], 0)
        self.assertEqual(data['service_fee'], 0)
        self.assertEqual(data['service_fee_components'], [])

    def test_serializer_includes_conditional_zone_context_for_payment_order(self):
        table_session = self.create_table_session()
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            table_session=table_session,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            order_number=1,
            channel=Order.Channel.HALL,
            status=Order.Status.SUBMITTED,
            guest_count=2,
        )

        single_zone_data = OrderSerializer(order).data

        self.assertEqual(single_zone_data['table_number'], self.table.table_number)
        self.assertEqual(single_zone_data['zone_name'], self.zone.name)
        self.assertFalse(single_zone_data['show_zone_name'])

        ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name='VIP zona',
            sort_order=2,
        )

        multi_zone_data = OrderSerializer(order).data

        self.assertTrue(multi_zone_data['show_zone_name'])

    def test_serializer_includes_service_fee_percent_payments_and_receipts(self):
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save(update_fields=['vat_enabled', 'vat_percent'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=1,
            display_name='VIP stol',
            channel=Order.Channel.HALL,
            status=Order.Status.CLOSED,
            guest_count=2,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
            status=OrderItem.Status.DONE,
        )
        order.recalculate_totals()
        payment = Payment.objects.create(
            order=order,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=order.total,
            status=Payment.Status.SUCCEEDED,
        )
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            provider='mock',
            payload={'receipt_number': 'R-1'},
        )

        data = OrderSerializer(order).data

        self.assertEqual(data['service_fee'], 3000)
        self.assertTrue(data['service_fee_enabled'])
        self.assertEqual(data['service_fee_percent'], 10)
        self.assertTrue(data['vat_enabled'])
        self.assertEqual(data['vat_percent'], 12)
        self.assertEqual(data['vat_amount'], 3536)
        self.assertEqual(data['display_name'], 'VIP stol')
        self.assertEqual(data['channel'], Order.Channel.HALL)
        self.assertEqual(len(data['payments']), 1)
        self.assertEqual(data['payments'][0]['id'], str(payment.id))
        self.assertEqual(len(data['receipts']), 1)
        self.assertEqual(data['receipts'][0]['id'], str(receipt.id))
