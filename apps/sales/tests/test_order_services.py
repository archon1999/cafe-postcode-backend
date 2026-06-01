from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from apps.floor.models import DiningTable, TableSession
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order, OrderItem
from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.billing.services import CashShiftService, OrderPaymentService, PaymentRefundService
from apps.restaurants.models import DistributionPoint
from apps.sales.services import OrderStateService, OrderSubmissionService
from apps.sales.tests.support.pos_api import PosTestCase


class OrderStateServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.service = OrderStateService()

    def test_next_order_number_increments_branch_counter(self):
        first_number = self.service.next_order_number(branch=self.branch)
        second_number = self.service.next_order_number(branch=self.branch)

        self.branch.refresh_from_db()
        self.assertEqual(first_number, 1)
        self.assertEqual(second_number, 2)
        self.assertEqual(self.branch.last_order_number, 2)

    def test_ensure_session_accepts_new_order_rejects_existing_active_order(self):
        session = self.create_table_session()
        Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            table_session=session,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            order_number=1,
            channel=Order.Channel.HALL,
            status=Order.Status.SUBMITTED,
            guest_count=session.guest_count,
        )

        with self.assertRaises(ValidationError):
            self.service.ensure_session_accepts_new_order(table_session=session)

    def test_close_order_after_payment_closes_session_and_releases_table(self):
        session = self.create_table_session(status=TableSession.Status.PENDING_PAYMENT)
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            table_session=session,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            order_number=1,
            channel=Order.Channel.HALL,
            status=Order.Status.READY,
            guest_count=session.guest_count,
        )

        self.service.close_order_after_payment(order=order, received_by=self.user)

        order.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)


class OrderPaymentServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.service = OrderPaymentService()
        self.delivery_distribution = DistributionPoint.objects.create(
            restaurant=self.restaurant,
            name='Delivery',
            kind=DistributionPoint.Kind.DELIVERY,
        )

    def _create_order_with_item(self, *, channel, quantity=1, table_session=None, delivery_details=True):
        distribution_point = self.takeaway_distribution
        if channel == Order.Channel.HALL:
            distribution_point = self.hall_distribution
        if channel == Order.Channel.DELIVERY:
            distribution_point = self.delivery_distribution

        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            table_session=table_session,
            distribution_point=distribution_point,
            opened_by=self.user,
            order_number=1,
            channel=channel,
            status=Order.Status.OPEN,
            guest_count=table_session.guest_count if table_session else 1,
            delivery_phone='90-123-45-67' if channel == Order.Channel.DELIVERY and delivery_details else '',
            delivery_address='Chilonzor 12' if channel == Order.Channel.DELIVERY and delivery_details else '',
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=quantity,
            unit_price=30000,
        )
        order.recalculate_totals()
        return order

    def test_process_hall_payment_applies_branch_service_fee_and_creates_receipt(self):
        session = self.create_table_session()
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        order = self._create_order_with_item(channel=Order.Channel.HALL, table_session=session)

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal:
            issue_fiscal.return_value = [{'ok': True, 'provider': 'unikassa'}]
            result = self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': 33000},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        order.refresh_from_db()
        session.refresh_from_db()
        self.table.refresh_from_db()
        self.assertEqual(order.subtotal, 30000)
        self.assertEqual(order.total, 33000)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(result['payment'].status, Payment.Status.SUCCEEDED)
        self.assertEqual(result['receipt'].status, Receipt.Status.SENT)
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)

    def test_process_takeaway_payment_applies_service_fee_when_enabled(self):
        order = self._create_order_with_item(channel=Order.Channel.TAKEAWAY, quantity=2)

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal:
            issue_fiscal.return_value = [{'ok': True, 'provider': 'unikassa'}]
            result = self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        order.refresh_from_db()
        self.assertEqual(order.subtotal, 60000)
        self.assertEqual(order.total, 66000)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(result['receipt'].status, Receipt.Status.SENT)
        self.assertEqual(order.receipts.count(), 1)

    def test_process_rejects_partial_payment(self):
        order = self._create_order_with_item(channel=Order.Channel.TAKEAWAY, quantity=2)

        with self.assertRaises(ValidationError):
            self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': 30000},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

    def test_process_takeaway_payment_routes_to_kitchen_only_after_success(self):
        order = self._create_order_with_item(channel=Order.Channel.TAKEAWAY)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

        result = self.service.process(
            order=order,
            payload={'method': Payment.Method.CASH, 'amount': order.total},
            received_by=self.user,
            cash_shift=self.create_cash_shift(),
        )

        order.refresh_from_db()
        self.assertEqual(result['payment'].status, Payment.Status.SUCCEEDED)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertTrue(KitchenTicket.objects.filter(order=order, prep_station=self.prep_station).exists())

    def test_process_takeaway_failed_payment_keeps_order_open_without_kitchen_ticket(self):
        order = self._create_order_with_item(channel=Order.Channel.TAKEAWAY)

        with patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': False, 'detail': 'declined'}):
            result = self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        order.refresh_from_db()
        self.assertEqual(result['payment'].status, Payment.Status.FAILED)
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    def test_process_delivery_payment_submits_before_payment(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

        with patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': False, 'detail': 'declined'}):
            result = self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        order.refresh_from_db()
        self.assertEqual(result['payment'].status, Payment.Status.FAILED)
        self.assertEqual(order.status, Order.Status.SUBMITTED)
        self.assertTrue(KitchenTicket.objects.filter(order=order, prep_station=self.prep_station).exists())

    def test_process_delivery_payment_receipt_payload_includes_delivery_details(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY)

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal:
            issue_fiscal.return_value = [{'ok': True, 'provider': 'unikassa', 'receipt_number': 'R-1'}]
            result = self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        payload = result['receipt'].payload
        self.assertEqual(payload['delivery_phone'], '90-123-45-67')
        self.assertEqual(payload['delivery_address'], 'Chilonzor 12')

    def test_delivery_submit_rejects_missing_delivery_details(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY, delivery_details=False)

        with self.assertRaises(ValidationError):
            OrderSubmissionService().submit(order)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    def test_delivery_submit_rejects_invalid_delivery_phone(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY)
        order.delivery_phone = '901234567'
        order.save(update_fields=['delivery_phone', 'updated_at'])

        with self.assertRaises(ValidationError):
            OrderSubmissionService().submit(order)

    def test_delivery_submit_succeeds_with_delivery_details(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY)

        OrderSubmissionService().submit(order)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SUBMITTED)
        self.assertTrue(KitchenTicket.objects.filter(order=order, prep_station=self.prep_station).exists())

    def test_process_delivery_payment_rejects_missing_delivery_details(self):
        order = self._create_order_with_item(channel=Order.Channel.DELIVERY, delivery_details=False)

        with self.assertRaises(ValidationError):
            self.service.process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total},
                received_by=self.user,
                cash_shift=self.create_cash_shift(),
            )

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())
        self.assertFalse(Payment.objects.filter(order=order).exists())


class CashShiftServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.service = CashShiftService()

    def test_open_shift_creates_active_shift(self):
        shift = self.service.open_shift(
            branch=self.branch,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            opening_cash_amount=250000,
            notes_open='Morning shift',
        )

        self.assertEqual(shift.status, shift.Status.OPEN)
        self.assertEqual(shift.opening_cash_amount, 250000)
        self.assertEqual(shift.cash_desk_id, self.cash_desk.id)

    def test_close_shift_captures_expected_cash_snapshot(self):
        shift = self.create_cash_shift(opening_cash_amount=100000)
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=10,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
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
        )

        self.service.close_shift(
            shift=shift,
            actual_closing_cash_amount=135000,
            closed_by=self.user,
            notes_close='Closing shift',
        )

        shift.refresh_from_db()
        self.assertEqual(shift.status, shift.Status.CLOSED)
        self.assertEqual(shift.expected_closing_cash_amount, 140000)
        self.assertEqual(shift.cash_difference_amount, -5000)
        self.assertEqual(shift.cash_total, 40000)


class PaymentRefundServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.payment_service = OrderPaymentService()
        self.refund_service = PaymentRefundService()

    def test_refund_creates_refund_record_and_receipt(self):
        shift = self.create_cash_shift()
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=11,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
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
        result = self.payment_service.process(
            order=order,
            payload={'method': Payment.Method.CASH, 'amount': order.total},
            received_by=self.user,
            cash_shift=shift,
        )

        refund_result = self.refund_service.refund(
            payment=result['payment'],
            refunded_by=self.user,
            cash_shift=shift,
            reason='Customer cancelled',
        )

        self.assertEqual(refund_result['refund'].status, PaymentRefund.Status.SUCCEEDED)
        self.assertEqual(refund_result['refund'].amount, order.total)
        self.assertEqual(refund_result['receipt'].kind, Receipt.Kind.REFUND)
        self.assertTrue(result['payment'].refunds.filter(status=PaymentRefund.Status.SUCCEEDED).exists())

    def test_reprint_increments_receipt_counter(self):
        shift = self.create_cash_shift()
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=12,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
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
        with (
            patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': True, 'reference': ''}),
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal,
            patch('apps.billing.services.payment_refund.reprint_fiscal_receipt') as reprint_fiscal,
        ):
            issue_fiscal.return_value = [{'ok': True, 'provider': 'unikassa'}]
            reprint_fiscal.return_value = {'ok': True, 'provider': 'unikassa'}
            result = self.payment_service.process(
                order=order,
                payload={'method': Payment.Method.CARD, 'amount': order.total},
                received_by=self.user,
                cash_shift=shift,
            )
            receipt = result['receipt']

            self.refund_service.reprint(receipt=receipt, cash_shift=shift)

        receipt.refresh_from_db()
        self.assertEqual(receipt.reprint_count, 1)
        self.assertIsNotNone(receipt.last_reprinted_at)
