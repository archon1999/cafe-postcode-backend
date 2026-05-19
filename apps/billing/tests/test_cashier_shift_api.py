from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from apps.billing.models import CashShift, FiscalShiftSession, Payment, PaymentRefund, Receipt
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
        self.assertEqual(current_shift['expected_closing_cash_amount'], 150000)

        shift = CashShift.objects.get(pk=current_shift['id'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=77,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )

        context_response = self.client.get('/api/v1/pos/billing/context/')
        self.assertEqual(context_response.status_code, status.HTTP_200_OK, context_response.data)
        self.assertEqual(context_response.data['current_shift']['cash_total'], 40000)
        self.assertEqual(context_response.data['current_shift']['expected_closing_cash_amount'], 190000)

        close_response = self.close_shift_via_api(actual_closing_cash_amount=185000, notes_close='Cash mismatch')

        self.assertIsNone(close_response['current_shift'])
        shift.refresh_from_db()
        self.assertEqual(shift.status, CashShift.Status.CLOSED)
        self.assertEqual(shift.cash_difference_amount, -5000)

    def test_close_last_cash_shift_can_close_fiscal_shift(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='unikassa',
            terminal_id='LG420',
            opened_at=timezone.now(),
        )

        with patch('apps.billing.services.cash_shift.close_fiscal_shift') as close_fiscal:
            close_fiscal.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            response = self.client.post(
                '/api/v1/pos/billing/shifts/current/close/',
                {
                    'actual_closing_cash_amount': 150000,
                    'notes_close': '',
                    'close_fiscal_shift': True,
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn('fiscal_shift', response.data)
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)
        session = FiscalShiftSession.objects.get(restaurant=self.restaurant)
        self.assertEqual(session.status, FiscalShiftSession.Status.CLOSED)

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

