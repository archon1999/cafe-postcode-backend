from apps.sales.models import Order, OrderItem
from apps.billing.models import Payment, Receipt
from apps.floor.models import ZoneOrCabin
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase


class OrderSerializerTests(PosTestCase):
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
