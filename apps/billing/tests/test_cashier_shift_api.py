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
        self.assertTrue(response.data['restaurant_fiscal_profile']['service_fee_enabled'])
        self.assertEqual(response.data['restaurant_fiscal_profile']['service_fee_percent'], '10.00')
        self.assertEqual(len(response.data['available_cash_desks']), 1)
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration'])
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration_name'])
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration_printer_name'])
        self.assertIsNone(response.data['current_shift'])
        self.assertFalse(response.data['fiscal_shift_open'])

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

    def test_current_shift_summary_uses_mixed_payment_cash_breakdown(self):
        open_response = self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)
        shift = CashShift.objects.get(pk=open_response['current_shift']['id'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=78,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=33000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=33000,
            cash_amount=20000,
            card_amount=13000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )

        context_response = self.client.get('/api/v1/pos/billing/context/')

        self.assertEqual(context_response.status_code, status.HTTP_200_OK, context_response.data)
        self.assertEqual(context_response.data['current_shift']['cash_total'], 20000)
        self.assertEqual(context_response.data['current_shift']['card_total'], 13000)
        self.assertEqual(context_response.data['current_shift']['expected_closing_cash_amount'], 170000)

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

    def test_close_cash_shift_skips_fiscal_close_when_fiscal_shift_was_not_opened(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)

        with patch('apps.billing.services.cash_shift.close_fiscal_shift') as close_fiscal:
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
        close_fiscal.assert_not_called()
        self.assertNotIn('fiscal_shift', response.data)
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)

    def test_close_fiscal_shift_with_unresolved_receipt_returns_clean_error(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='unikassa',
            terminal_id='LG420',
            opened_at=timezone.now(),
        )
        shift = CashShift.objects.get(cash_desk=self.cash_desk, status=CashShift.Status.OPEN)
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=78,
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
            register_fiscal=True,
            paid_at=timezone.now(),
        )

        response = self.client.post(
            '/api/v1/pos/billing/shifts/current/close/',
            {'close_fiscal_shift': True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Fiscalga yuborilmagan', response.data['detail'])
        self.assertIn('Yopilmagan hisoblar', response.data['detail'])
        self.assertEqual(int(response.data['unresolved_fiscal_count']), 1)

    def test_retry_fiscal_failure_returns_bad_request(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=79,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        payment = Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=timezone.now(),
        )

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal:
            issue_fiscal.return_value = [
                {
                    'ok': False,
                    'provider': 'unikassa',
                    'detail': 'Unikassa request failed: illegal request line',
                    'split_reason': 'none',
                }
            ]
            response = self.client.post(f'/api/v1/pos/billing/payments/{payment.id}/retry-fiscal/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Unikassa request failed: illegal request line')
        self.assertFalse(response.data['results'][0]['ok'])

    def test_refund_and_print_document_endpoints_work_for_closed_paid_order(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        order_payload = self.create_order_via_api({'channel': 'takeaway'})
        self.add_item_via_api(order_payload['id'], quantity=1)

        with (
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal,
            patch('apps.billing.services.payment_refund.issue_refund_receipt') as refund_fiscal,
        ):
            issue_fiscal.return_value = [
                {
                    'ok': True,
                    'provider': 'unikassa',
                    'receipt_number': '1001',
                    'response': {'ReceiptSeq': 1001},
                    'split_reason': 'none',
                }
            ]
            refund_fiscal.return_value = {
                'ok': True,
                'provider': 'unikassa',
                'receipt_number': '1002',
            }
            order = Order.objects.get(pk=order_payload['id'])
            payment_response = self.pay_order_via_api(order_payload['id'], method='cash', amount=order.total)
            Receipt.objects.filter(pk=payment_response['receipt']['id']).delete()
            print_document_response = self.client.post(
                f"/api/v1/pos/billing/payments/{payment_response['payment']['id']}/print-document/"
            )
            self.assertEqual(print_document_response.status_code, status.HTTP_200_OK)
            self.assertIsNotNone(print_document_response.data['receipt']['print_document'])
            self.assertEqual(print_document_response.data['receipt']['kind'], Receipt.Kind.PLAIN)

            refund_response = self.refund_payment_via_api(payment_response['payment']['id'], reason='Customer returned order')

        order = Order.objects.get(pk=order_payload['id'])
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(refund_response['receipt']['kind'], Receipt.Kind.REFUND)
        self.assertIsNotNone(refund_response['receipt']['print_document'])
        self.assertTrue(
            PaymentRefund.objects.filter(payment_id=payment_response['payment']['id'], status=PaymentRefund.Status.SUCCEEDED).exists()
        )

