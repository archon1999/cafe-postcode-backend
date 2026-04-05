from rest_framework import status

from apps.billing.models import CashShift, PaymentRefund, Receipt
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class CashierShiftApiTests(PosAPITestCase):
    def test_cashier_context_returns_restaurant_fiscal_profile_and_cash_desks(self):
        response = self.client.get('/api/v1/pos/billing/context/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['restaurant_fiscal_profile']['legal_name'], self.branch.legal_name)
        self.assertEqual(response.data['restaurant_fiscal_profile']['tax_number'], self.branch.tax_number)
        self.assertEqual(len(response.data['available_cash_desks']), 1)
        self.assertIsNone(response.data['current_shift'])

    def test_open_and_close_shift_flow_returns_current_shift_summary(self):
        open_response = self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)

        current_shift = open_response['current_shift']
        self.assertIsNotNone(current_shift)
        self.assertEqual(str(current_shift['cash_desk']), str(self.cash_desk.id))
        self.assertEqual(current_shift['opening_cash_amount'], 150000)

        close_response = self.close_shift_via_api(actual_closing_cash_amount=145000, notes_close='Cash mismatch')

        self.assertIsNone(close_response['current_shift'])
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)
        self.assertEqual(shift.cash_difference_amount, -5000)

    def test_refund_and_reprint_endpoints_work_for_closed_paid_order(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        order_payload = self.create_order_via_api({'channel': 'takeaway'})
        self.add_item_via_api(order_payload['id'], quantity=1)
        payment_response = self.pay_order_via_api(order_payload['id'], method='cash', amount=30000)

        reprint_response = self.reprint_receipt_via_api(payment_response['receipt']['id'])
        self.assertIn('receipt', reprint_response)

        refund_response = self.refund_payment_via_api(payment_response['payment']['id'], reason='Customer returned order')

        order = Order.objects.get(pk=order_payload['id'])
        receipt = Receipt.objects.get(pk=payment_response['receipt']['id'])
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(receipt.reprint_count, 1)
        self.assertEqual(refund_response['receipt']['kind'], Receipt.Kind.REFUND)
        self.assertTrue(
            PaymentRefund.objects.filter(payment_id=payment_response['payment']['id'], status=PaymentRefund.Status.SUCCEEDED).exists()
        )

