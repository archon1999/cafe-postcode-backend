from apps.sales.models import Order, OrderItem
from apps.billing.models import Payment, Receipt
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase


class OrderSerializerTests(PosTestCase):
    def test_serializer_includes_service_fee_percent_payments_and_receipts(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=1,
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
        self.assertEqual(data['service_fee_percent'], 10)
        self.assertEqual(data['channel'], Order.Channel.HALL)
        self.assertEqual(len(data['payments']), 1)
        self.assertEqual(data['payments'][0]['id'], str(payment.id))
        self.assertEqual(len(data['receipts']), 1)
        self.assertEqual(data['receipts'][0]['id'], str(receipt.id))
