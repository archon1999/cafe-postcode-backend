from unittest.mock import patch

from rest_framework import status

from apps.billing.models import Payment, Receipt
from apps.printing.models import PrintTemplate
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import Permission


class BackendPaymentScenarioTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.create_cash_shift()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={"ok": True, "provider": "cash", "reference": "cash-precheck"},
    )
    def test_full_cash_precheck_closes_once_and_creates_plain_document(
        self, charge_payment
    ):
        self._allow_precheck()
        order = self._order_with_items(quantity=2)

        response = self._pay(
            order,
            method=Payment.Method.CASH,
            amount=order.total,
            register_fiscal=False,
            operation_id="precheck-full-cash",
        )

        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        receipt = Receipt.objects.get(order=order)
        self.assertEqual(response.data["payment"]["id"], str(payment.id))
        self.assertEqual(
            self._payment_state(order),
            {
                "orderStatus": Order.Status.CLOSED,
                "total": 66000,
                "paid": 66000,
                "remaining": 0,
                "cash": 66000,
                "card": 0,
                "payments": 1,
                "receipts": 1,
            },
        )
        self.assertEqual(payment.edge_operation_id, "precheck-full-cash")
        self.assertFalse(payment.register_fiscal)
        self.assertEqual(
            (receipt.kind, receipt.status), (Receipt.Kind.PLAIN, Receipt.Status.CREATED)
        )
        self.assertEqual(
            receipt.print_document.kind, PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN
        )
        charge_payment.assert_called_once()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={
            "ok": True,
            "provider": "characterization",
            "reference": "split-precheck",
        },
    )
    def test_sequential_precheck_split_preserves_partial_and_aggregates_final_totals(
        self, charge_payment
    ):
        self._allow_precheck()
        order = self._order_with_items(quantity=1)

        partial = self._pay(
            order,
            method=Payment.Method.CASH,
            amount=20000,
            register_fiscal=False,
            operation_id="precheck-split-cash",
        )

        order.refresh_from_db()
        self.assertIsNone(partial.data["receipt"])
        self.assertEqual(
            self._payment_state(order),
            {
                "orderStatus": Order.Status.SUBMITTED,
                "total": 33000,
                "paid": 20000,
                "remaining": 13000,
                "cash": 20000,
                "card": 0,
                "payments": 1,
                "receipts": 0,
            },
        )

        completed = self._pay(
            order,
            method=Payment.Method.CARD,
            amount=13000,
            register_fiscal=False,
            operation_id="precheck-split-card",
        )

        order.refresh_from_db()
        receipt = Receipt.objects.get(order=order)
        self.assertEqual(
            self._payment_state(order),
            {
                "orderStatus": Order.Status.CLOSED,
                "total": 33000,
                "paid": 33000,
                "remaining": 0,
                "cash": 20000,
                "card": 13000,
                "payments": 2,
                "receipts": 1,
            },
        )
        self.assertEqual(completed.data["receipt"]["id"], str(receipt.id))
        self.assertEqual(receipt.kind, Receipt.Kind.PLAIN)
        self.assertEqual(receipt.payload["payment_method"], "Aralash")
        self.assertEqual(
            (receipt.payload["cash_amount"], receipt.payload["card_amount"]),
            (20000, 13000),
        )
        self.assertEqual(
            list(
                Payment.objects.filter(order=order)
                .order_by("created_at")
                .values_list("edge_operation_id", flat=True)
            ),
            ["precheck-split-cash", "precheck-split-card"],
        )
        self.assertEqual(charge_payment.call_count, 2)

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={
            "ok": True,
            "provider": "cash",
            "reference": "idempotent-payment",
        },
    )
    def test_same_operation_replays_one_payment_while_a_distinct_closed_order_retry_is_rejected(
        self, charge_payment
    ):
        order = self._order_with_items(quantity=1)
        payload = {
            "method": Payment.Method.CASH,
            "amount": order.total,
            "registerFiscal": True,
            "edgeOperationId": "payment-replay-one",
        }

        first = self.client.post(self._payment_url(order), payload, format="json")
        replay = self.client.post(self._payment_url(order), payload, format="json")
        distinct_retry = self.client.post(
            self._payment_url(order),
            {**payload, "edgeOperationId": "payment-replay-two"},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(replay.status_code, status.HTTP_201_CREATED, replay.data)
        self.assertEqual(first.data["payment"]["id"], replay.data["payment"]["id"])
        self.assertEqual(
            distinct_retry.status_code, status.HTTP_400_BAD_REQUEST, distinct_retry.data
        )
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        charge_payment.assert_called_once()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={
            "ok": True,
            "provider": "cash",
            "reference": "direct-header-replay",
        },
    )
    def test_direct_header_operation_replays_one_payment(self, charge_payment):
        self._allow_precheck()
        order = self._order_with_items(quantity=1)
        payload = {
            "method": Payment.Method.CASH,
            "amount": order.total,
            "registerFiscal": False,
        }
        header = {"HTTP_X_EDGE_OPERATION_ID": "direct-header-payment-replay"}

        first = self.client.post(
            self._payment_url(order), payload, format="json", **header
        )
        replay = self.client.post(
            self._payment_url(order), payload, format="json", **header
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(replay.status_code, status.HTTP_201_CREATED, replay.data)
        self.assertEqual(first.data["payment"]["id"], replay.data["payment"]["id"])
        self.assertEqual(first.data["receipt"]["id"], replay.data["receipt"]["id"])
        payment = Payment.objects.get(order=order)
        self.assertEqual(payment.edge_operation_id, "direct-header-payment-replay")
        charge_payment.assert_called_once()

    @patch(
        "apps.billing.services.order_payment.charge_payment",
        return_value={
            "ok": True,
            "provider": "cash",
            "reference": "must-not-charge-conflicting-operation",
        },
    )
    def test_conflicting_header_and_body_operation_ids_are_rejected_before_charge(
        self, charge_payment
    ):
        self._allow_precheck()
        order = self._order_with_items(quantity=1)

        response = self.client.post(
            self._payment_url(order),
            {
                "method": Payment.Method.CASH,
                "amount": order.total,
                "registerFiscal": False,
                "edgeOperationId": "body-payment-operation",
            },
            format="json",
            HTTP_X_EDGE_OPERATION_ID="header-payment-operation",
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertIn("edgeOperationId", response.data)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())
        charge_payment.assert_not_called()

    @patch("apps.billing.services.order_payment.charge_payment")
    def test_precheck_requires_explicit_skip_permission_before_any_charge(
        self, charge_payment
    ):
        order = self._order_with_items(quantity=1)

        response = self.client.post(
            self._payment_url(order),
            {
                "method": Payment.Method.CASH,
                "amount": order.total,
                "registerFiscal": False,
                "edgeOperationId": "precheck-without-permission",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertIn("register_fiscal", response.data)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())
        charge_payment.assert_not_called()

    def _order_with_items(self, *, quantity):
        payload = self.create_order_via_api(
            {
                "distributionPoint": str(self.takeaway_distribution.id),
                "channel": Order.Channel.TAKEAWAY,
                "guestCount": 1,
            }
        )
        self.add_item_via_api(payload["id"], quantity=quantity)
        return Order.objects.get(pk=payload["id"])

    def _pay(self, order, *, method, amount, register_fiscal, operation_id):
        response = self.client.post(
            self._payment_url(order),
            {
                "method": method,
                "amount": amount,
                "registerFiscal": register_fiscal,
                "edgeOperationId": operation_id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    @staticmethod
    def _payment_url(order):
        return f"/api/v1/pos/billing/orders/{order.id}/pay/"

    @staticmethod
    def _payment_state(order):
        payments = Payment.objects.filter(order=order, status=Payment.Status.SUCCEEDED)
        paid = sum(payment.amount for payment in payments)
        return {
            "orderStatus": order.status,
            "total": order.total,
            "paid": paid,
            "remaining": order.total - paid,
            "cash": sum(payment.cash_amount for payment in payments),
            "card": sum(payment.card_amount for payment in payments),
            "payments": payments.count(),
            "receipts": Receipt.objects.filter(order=order).count(),
        }

    def _allow_precheck(self):
        permission, _ = Permission.objects.get_or_create(
            code="pos_fiscal_receipts.skip",
            defaults={
                "name": "Skip fiscal receipt",
                "description": "Skip fiscal receipt",
            },
        )
        self.role.permissions.add(permission)
        self.entitlement.permissions.add(permission)
