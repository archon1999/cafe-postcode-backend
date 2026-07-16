from unittest.mock import patch

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import Payment, Receipt
from apps.billing.services import OrderPaymentService, PaymentFiscalRetryService
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase


class BackendFiscalScenarioTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.shift = self.create_cash_shift()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={"ok": True, "provider": "cash", "reference": "fiscal-success"},
    )
    def test_success_closes_order_and_creates_sent_fiscal_document(self, charge_payment):
        order = self._open_order_with_item(order_number=601)
        fiscal_result = self._fiscal_result(order=order, ok=True, receipt_number="601")

        with patch.object(
            OrderPaymentService, "_issue_fiscal_receipts", return_value=[fiscal_result]
        ) as issue_fiscal:
            result = self._pay_fiscally(order)

        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        receipt = Receipt.objects.get(order=order)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(payment.register_fiscal)
        self.assertEqual((receipt.kind, receipt.status), (Receipt.Kind.FISCAL, Receipt.Status.SENT))
        self.assertEqual(receipt.payload["receipt_number"], "601")
        self.assertEqual(receipt.payload["order_label"], "#601")
        self.assertIsNotNone(receipt.print_document_id)
        self.assertEqual(result["receipt"], receipt)
        charge_payment.assert_called_once()
        issue_fiscal.assert_called_once()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={"ok": True, "provider": "cash", "reference": "fiscal-failure"},
    )
    def test_provider_failure_keeps_paid_order_closed_with_retryable_failed_receipt(self, charge_payment):
        order = self._open_order_with_item(order_number=602)
        fiscal_result = self._fiscal_result(
            order=order,
            ok=False,
            code="DEVICE_LOCKED",
            detail="Fiscal Drive is locked.",
        )

        with patch.object(
            OrderPaymentService, "_issue_fiscal_receipts", return_value=[fiscal_result]
        ):
            result = self._pay_fiscally(order)

        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        receipt = Receipt.objects.get(order=order)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(payment.register_fiscal)
        self.assertEqual((receipt.kind, receipt.status), (Receipt.Kind.FISCAL, Receipt.Status.FAILED))
        self.assertEqual(receipt.fiscal_error_code, "DEVICE_LOCKED")
        self.assertEqual(receipt.fiscal_error_message, "Fiscal Drive is locked.")
        self.assertIsNone(receipt.print_document_id)
        self.assertEqual(result["receipts"], [receipt])
        self.assertFalse(Receipt.objects.filter(order=order, kind=Receipt.Kind.PLAIN).exists())
        charge_payment.assert_called_once()

    @patch("apps.billing.services.order_payment.charge_payment")
    def test_untrusted_edge_fiscal_result_is_rejected_before_payment_or_provider(self, charge_payment):
        order = self._open_order_with_item(order_number=603)

        with self.assertRaises(ValidationError) as raised:
            OrderPaymentService().process(
                order=order,
                payload={
                    "method": Payment.Method.CASH,
                    "amount": order.total,
                    "register_fiscal": True,
                    "edge_fiscal_results": [self._fiscal_result(order=order, ok=True)],
                },
                received_by=self.user,
                cash_shift=self.shift,
                trusted_edge_replay=False,
            )

        self.assertIn("edgeFiscalResults", raised.exception.detail)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())
        charge_payment.assert_not_called()

    @patch("apps.billing.services.order_payment.issue_fiscal_receipts")
    def test_sent_receipt_retry_replays_without_provider_and_restores_document(self, issue_fiscal):
        order, payment = self._closed_order_payment(order_number=604)
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            provider="fiscal-drive-service",
            payload=self._fiscal_result(order=order, ok=True, receipt_number="604"),
            fiscal_requested_at=timezone.now(),
            fiscal_registered_at=timezone.now(),
        )

        replayed = PaymentFiscalRetryService().retry(payment=payment)

        receipt.refresh_from_db()
        self.assertEqual(replayed["receipt"], receipt)
        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 1)
        self.assertIsNotNone(receipt.print_document_id)
        issue_fiscal.assert_not_called()

    @patch("apps.billing.services.order_payment.issue_fiscal_receipts")
    def test_partial_split_without_failed_reason_blocks_retry_before_provider(self, issue_fiscal):
        order, payment = self._closed_order_payment(order_number=605)
        sent = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={"ok": True, "split_reason": "cash_allowed"},
        )
        failed = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.FAILED,
            payload={"ok": False, "detail": "missing split metadata"},
        )

        with self.assertRaises(ValidationError):
            PaymentFiscalRetryService().retry(payment=payment)

        sent.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual((sent.status, failed.status), (Receipt.Status.SENT, Receipt.Status.FAILED))
        issue_fiscal.assert_not_called()

    def _pay_fiscally(self, order):
        return OrderPaymentService().process(
            order=order,
            payload={
                "method": Payment.Method.CASH,
                "amount": order.total,
                "register_fiscal": True,
            },
            received_by=self.user,
            cash_shift=self.shift,
        )

    def _open_order_with_item(self, *, order_number):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=order_number,
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
        return order

    def _closed_order_payment(self, *, order_number):
        order = self._open_order_with_item(order_number=order_number)
        order.status = Order.Status.CLOSED
        order.closed_at = timezone.now()
        order.save(update_fields=["status", "closed_at", "updated_at"])
        payment = Payment.objects.create(
            order=order,
            cash_shift=self.shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=order.total,
            cash_amount=order.total,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=timezone.now(),
        )
        return order, payment

    @staticmethod
    def _fiscal_result(order, *, ok, receipt_number="", code="", detail=""):
        now = timezone.now().isoformat()
        return {
            "ok": ok,
            "provider": "fiscal-drive-service",
            "receipt_number": receipt_number,
            "terminal_id": "TERM-1",
            "code": code,
            "detail": detail,
            "fiscal_requested_at": now,
            "fiscal_registered_at": now if ok else None,
            "response": {"TerminalID": "TERM-1", "ReceiptSeq": receipt_number},
            "request": {
                "receipt": {"ReceivedCash": int(order.total or 0) * 100, "ReceivedCard": 0}
            },
        }
