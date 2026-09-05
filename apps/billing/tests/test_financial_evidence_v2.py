from datetime import timedelta
import uuid
from unittest.mock import patch

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import CashShift, Payment, Receipt, FiscalReceiptAttempt
from apps.billing.services import (
    CashShiftService,
    OrderPaymentService,
    PaymentFiscalRetryService,
    PaymentRefundService,
)
from apps.billing.services.edge_shift_recovery import resolve_trusted_edge_payment_shift
from apps.billing.services.fiscal_evidence import persist_fiscal_evidence
from apps.integrations.models import IntegrationConfig
from apps.kitchen.services.kitchen_status import KitchenStatusService
from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase


class FinancialEvidenceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.integration = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name="Fiscal test",
            kind="fiscal",
            provider="fiscal-drive-service",
        )
        self.cash_desk.fiscal_integration = self.integration
        self.cash_desk.save()
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.shift = self.create_cash_shift()
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            distribution_point=self.takeaway_distribution,
            channel="takeaway",
            order_number=901,
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        self.order.recalculate_totals()
        self.print_patch = patch(
            "apps.billing.services.fiscal_evidence.attach_receipt_print_document"
        )
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

    def evidence(self, amount=30000, number="100", split="default", **extra):
        return {
            "ok": True,
            "provider": "fiscal-drive-service",
            "terminal_id": "TEST-T1",
            "receipt_number": number,
            "split_reason": split,
            "response": {
                "DateTime": "2026-09-05 01:00:00",
                "ReceiptSeq": number,
                "TerminalID": "TEST-T1",
            },
            "request": {"receipt": {"ReceivedCash": amount * 100, "ReceivedCard": 0}},
            **extra,
        }

    def pay(self, results=None, occurred_at=None):
        return OrderPaymentService().process(
            order=self.order,
            cash_shift=self.shift,
            received_by=self.user,
            trusted_edge_replay=True,
            occurred_at=occurred_at,
            payload={
                "method": "cash",
                "amount": 30000,
                "register_fiscal": True,
                "edge_operation_id": "payment:" + str(uuid.uuid4()),
                "edge_fiscal_results": results
                if results is not None
                else [self.evidence()],
            },
        )

    def test_historical_payment_keeps_original_closed_shift_and_event_time(self):
        occurred = timezone.now() - timedelta(days=2)
        self.shift.status = "closed"
        self.shift.closed_at = occurred + timedelta(hours=1)
        self.shift.save()
        successor = self.create_cash_shift()
        resolved = resolve_trusted_edge_payment_shift(
            restaurant=self.restaurant,
            edge_cash_shift_id=self.shift.pk,
            occurred_at=occurred,
        )
        self.assertEqual(resolved.pk, self.shift.pk)
        result = self.pay(occurred_at=occurred)
        payment = result["payment"]
        self.assertEqual(payment.cash_shift_id, self.shift.pk)
        self.assertNotEqual(payment.cash_shift_id, successor.pk)
        self.assertEqual(payment.paid_at, occurred)
        self.assertEqual(payment.occurred_at, occurred)
        self.assertEqual(result["receipt"].original_paid_at, occurred)
        self.assertEqual(payment.financial_snapshot["orderTotal"], 30000)
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.reconciliation_payload["state"], "needs_review")
        self.assertIn(
            payment.edge_operation_id,
            self.shift.reconciliation_payload["lateOperationIds"],
        )

    def test_unknown_fiscal_payment_stays_fiscal_and_blocks_close(self):
        result = self.pay(
            [
                {
                    "ok": False,
                    "provider": "fiscal-drive-service",
                    "state": "unknown",
                    "code": "TIMEOUT",
                }
            ]
        )
        self.assertTrue(result["payment"].register_fiscal)
        self.assertEqual(result["receipt"].status, Receipt.Status.UNKNOWN)
        self.assertFalse(Receipt.objects.filter(kind="plain").exists())
        with self.assertRaises(ValidationError):
            CashShiftService().close_shift(
                shift=self.shift, actual_closing_cash_amount=None, closed_by=self.user
            )

    def test_partial_initial_and_retry_success_are_always_preserved(self):
        failed = {
            "ok": False,
            "provider": "fiscal-drive-service",
            "split_reason": "b",
            "definitive": True,
        }
        result = self.pay([self.evidence(12000, split="a"), failed])
        self.assertEqual({r.status for r in result["receipts"]}, {"sent", "failed"})
        PaymentFiscalRetryService().retry(
            payment=result["payment"],
            fiscal_results=[self.evidence(18000, number="101", split="b")],
        )
        self.assertEqual(Receipt.objects.filter(status="sent").count(), 2)
        self.assertEqual(FiscalReceiptAttempt.objects.count(), 3)

    def test_retry_from_no_success_retains_mixed_outcomes(self):
        result = self.pay(
            [
                {
                    "ok": False,
                    "provider": "fiscal-drive-service",
                    "state": "unknown",
                    "split_reason": "a",
                },
                {
                    "ok": False,
                    "provider": "fiscal-drive-service",
                    "definitive": True,
                    "split_reason": "b",
                },
            ]
        )
        PaymentFiscalRetryService().retry(
            payment=result["payment"],
            fiscal_results=[
                self.evidence(12000, split="a"),
                {
                    "ok": False,
                    "provider": "fiscal-drive-service",
                    "definitive": True,
                    "split_reason": "b",
                    "detail": "still rejected",
                },
            ],
        )
        self.assertEqual(Receipt.objects.filter(status="sent").count(), 1)
        self.assertEqual(Receipt.objects.filter(status="failed").count(), 1)

    def test_distinct_physical_receipt_cannot_replace_registered_split(self):
        result = self.pay()
        with self.assertRaises(ValidationError):
            persist_fiscal_evidence(
                payment=result["payment"], result=self.evidence(number="101")
            )
        self.assertEqual(Receipt.objects.get().payload["receipt_number"], "100")

    def test_retry_cannot_ack_distinct_receipt_when_already_registered(self):
        payment = self.pay()["payment"]
        with self.assertRaises(ValidationError):
            PaymentFiscalRetryService().retry(
                payment=payment, fiscal_results=[self.evidence(number="102")]
            )
        self.assertEqual(Receipt.objects.get().payload["receipt_number"], "100")

    def test_legacy_sent_receipt_also_requires_exact_physical_identity(self):
        payment = self.pay()['payment']
        Receipt.objects.update(registration_key=None, split_key='')
        with self.assertRaises(ValidationError):
            PaymentFiscalRetryService().retry(payment=payment, fiscal_results=[self.evidence(number='102')])
        self.assertEqual(Receipt.objects.get().payload['receipt_number'], '100')

    def test_retry_cannot_exceed_immutable_sale_total_with_new_split(self):
        payment = self.pay()["payment"]
        with self.assertRaises(ValidationError):
            PaymentFiscalRetryService().retry(
                payment=payment,
                fiscal_results=[self.evidence(number="102", split="another")],
            )
        self.assertEqual(Receipt.objects.count(), 1)

    def test_v2_trusted_payment_preserves_owner_payment_id(self):
        payment_id = uuid.uuid4()
        operation = {
            "operationId": "owner:" + str(uuid.uuid4()),
            "userId": str(self.user.pk),
            "eventVersion": 2,
            "ownerEpoch": "epoch1",
            "sequence": 1,
            "occurredAt": timezone.now().isoformat(),
            "method": "POST",
            "path": f"/api/v1/pos/billing/orders/{self.order.pk}/pay/",
            "body": {
                "amount": 30000,
                "method": "cash",
                "registerFiscal": True,
                "edgePaymentId": str(payment_id),
                "edgeCashShiftId": str(self.shift.pk),
                "edgeFiscalResults": [self.evidence()],
            },
        }
        result = LocalAgentMutationProcessor().process(
            agent=self.agent, operation=operation
        )
        self.assertTrue(result["applied"], result)
        self.assertEqual(Payment.objects.get().pk, payment_id)

    def test_partial_payment_retains_fiscal_intent_until_final_aggregate_receipt(self):
        first = OrderPaymentService().process(
            order=self.order,
            cash_shift=self.shift,
            received_by=self.user,
            trusted_edge_replay=True,
            payload={
                "method": "cash",
                "amount": 10000,
                "register_fiscal": True,
                "edge_operation_id": "partial:" + str(uuid.uuid4()),
            },
        )
        self.assertFalse(first["payment"].register_fiscal)
        self.assertTrue(first["payment"].financial_snapshot["fiscalRequested"])
        self.assertEqual(first["receipts"], [])
        final = OrderPaymentService().process(
            order=self.order,
            cash_shift=self.shift,
            received_by=self.user,
            trusted_edge_replay=True,
            payload={
                "method": "cash",
                "amount": 20000,
                "register_fiscal": True,
                "edge_operation_id": "final:" + str(uuid.uuid4()),
                "edge_fiscal_results": [self.evidence()],
            },
        )
        self.assertEqual(final["order"].status, "closed")
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(Receipt.objects.filter(status="sent").count(), 1)
        for payment in [first['payment'], final['payment']]:
            with self.assertRaises(ValidationError) as captured:
                PaymentRefundService().refund(payment=payment, refunded_by=self.user, cash_shift=self.shift,
                    trusted_edge_replay=True, refund_result={'ok': True, 'provider': 'local-edge'},
                    edge_operation_id='refund:' + str(uuid.uuid4()))
            self.assertEqual(str(captured.exception.detail['code']), 'FISCAL_REFUND_ALLOCATION_REQUIRED')

    def test_whole_order_refund_keeps_original_items_and_all_tender_identities(self):
        from copy import deepcopy
        from apps.billing.models import PaymentRefund
        original = self.evidence()
        original['response']['FiscalSign'] = '123'
        original['request']['receipt']['Items'] = [{'Name': 'Test', 'Price': 3000000, 'Count': 1000, 'VAT': 321429}]
        first = OrderPaymentService().process(order=self.order, cash_shift=self.shift, received_by=self.user,
            trusted_edge_replay=True, payload={'method': 'cash', 'amount': 10000, 'register_fiscal': True, 'edge_operation_id': 'part-one'})
        final = OrderPaymentService().process(order=self.order, cash_shift=self.shift, received_by=self.user,
            trusted_edge_replay=True, payload={'method': 'cash', 'amount': 20000, 'register_fiscal': True, 'edge_operation_id': 'part-two', 'edge_fiscal_results': [original]})
        reversal = deepcopy(original)
        reversal['receipt_number'] = '101'
        reversal['response']['ReceiptSeq'] = '101'
        reversal['request']['receipt'].update(Operation=1, RefundInfo={
            'TerminalID': 'TEST-T1', 'ReceiptSeq': '100', 'FiscalSign': '123', 'DateTime': '20260905010000'})
        identity = [{'paymentOperationId': p.edge_operation_id, 'refundId': str(uuid.uuid4()), 'amount': p.amount}
                    for p in (first['payment'], final['payment'])]
        kwargs = dict(payment=final['payment'], refunded_by=self.user, cash_shift=self.shift,
            trusted_edge_replay=True, refund_whole_order=True, refund_payments=identity,
            edge_operation_id='full-order-refund', refund_result={'ok': True, 'edgeOperationId': 'full-order-refund'})
        corrupted = deepcopy(reversal)
        corrupted['request']['receipt']['Items'][0]['VAT'] += 1
        with self.assertRaises(ValidationError):
            PaymentRefundService().refund(**kwargs, fiscal_results=[corrupted])
        self.assertFalse(PaymentRefund.objects.exists())
        result = PaymentRefundService().refund(**kwargs, fiscal_results=[reversal])
        self.assertEqual(PaymentRefund.objects.count(), 2)
        self.assertEqual(sum(PaymentRefund.objects.values_list('amount', flat=True)), 30000)
        self.assertEqual(Receipt.objects.filter(kind='refund', status='sent').count(), 1)
        self.assertEqual(result['receipt'].payload['request']['receipt']['Items'], original['request']['receipt']['Items'])
        replay = PaymentRefundService().refund(**kwargs, fiscal_results=[reversal])
        self.assertEqual(str(replay['refund'].pk), str(result['refund'].pk))
        self.assertEqual(PaymentRefund.objects.count(), 2)

    def test_successor_open_waits_for_predecessor_close_and_recovers_projection(self):
        service = CashShiftService()
        opening = self.shift.opened_at + timedelta(seconds=2)
        successor_id = uuid.uuid4()
        kwargs = dict(restaurant=self.restaurant, cash_desk=self.cash_desk, opened_by=self.user,
                      cashier=self.user, opening_cash_amount=1500, shift_id=successor_id,
                      opened_at=opening, trusted_edge_replay=True)
        with self.assertRaises(ValidationError) as error:
            service.open_shift(**kwargs)
        self.assertEqual(str(error.exception.detail['code']), 'SHIFT_PREDECESSOR_PENDING')
        self.assertFalse(CashShift.objects.filter(pk=successor_id).exists())
        service.close_shift(shift=self.shift, closed_by=self.user, actual_closing_cash_amount=0,
                            trusted_edge_replay=True, closed_at=opening - timedelta(seconds=1))
        # An existing projection materialized from delayed evidence must become
        # active only when its explicit original opening is replayed.
        successor = CashShift.objects.create(id=successor_id, cash_desk=self.cash_desk,
            cashier=self.user, opened_by=self.user, opened_at=opening, status=CashShift.Status.RECONCILING,
            reconciliation_payload={'materializedFromEvidence': True})
        self.assertEqual(service.open_shift(**kwargs).status, CashShift.Status.OPEN)
        successor.refresh_from_db()
        self.assertEqual(successor.opening_cash_amount, 1500)
        self.assertEqual(CashShift.objects.filter(cash_desk=self.cash_desk, status='open').count(), 1)

    def test_late_fiscal_open_and_close_do_not_replace_successor(self):
        from apps.billing.models import FiscalShiftSession

        service = CashShiftService()
        now = timezone.now()
        evidence = {
            "ok": True,
            "provider": "fiscal-drive-service",
            "terminal_id": "TEST-T1",
        }
        service.open_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            provider_result=evidence,
            occurred_at=now,
            session_key="current",
        )
        service.open_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            provider_result=evidence,
            occurred_at=now - timedelta(days=2),
            session_key="old",
        )
        self.assertEqual(
            service._get_active_fiscal_session(
                restaurant=self.restaurant, cash_desk=self.cash_desk
            ).edge_session_id,
            "current",
        )
        service.close_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            closed_by=self.user,
            provider_result=evidence,
            occurred_at=now - timedelta(days=1),
            session_key="old",
        )
        self.assertEqual(
            FiscalShiftSession.objects.get(edge_session_id="old").status, "closed"
        )
        self.assertEqual(
            FiscalShiftSession.objects.get(edge_session_id="current").status, "open"
        )

    def test_paid_order_total_cannot_be_changed_by_kitchen_or_recalculation(self):
        self.pay()
        with self.assertRaises(ValidationError):
            KitchenStatusService().update_item_status(
                item=self.item, status="cancelled", user=None
            )
        self.item.line_total = 0
        self.item.save(update_fields=["line_total"])
        self.order.recalculate_totals()
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 30000)

    def test_different_operation_for_paid_order_is_retained_for_review(self):
        self.pay()
        operation = {
            "operationId": "second:" + str(uuid.uuid4()),
            "userId": str(self.user.pk),
            "method": "POST",
            "path": f"/api/v1/pos/billing/orders/{self.order.pk}/pay/",
            "body": {
                "amount": 30000,
                "method": "cash",
                "registerFiscal": True,
                "edgeCashShiftId": str(self.shift.pk),
                "edgeFiscalResults": [self.evidence(number="101")],
            },
        }
        result = LocalAgentMutationProcessor().process(
            agent=self.agent, operation=operation
        )
        self.assertFalse(result["applied"])
        self.assertTrue(result["durablyReceived"])
        self.assertEqual(LocalAgentMutationInbox.objects.get().state, "needs_review")
        self.assertEqual(Payment.objects.count(), 1)

    def test_refund_uses_execution_shift_and_no_device_rpc(self):
        payment = self.pay()["payment"]
        refund_shift = self.create_cash_shift()
        occurred = timezone.now() - timedelta(minutes=10)
        with (
            patch("apps.billing.services.payment_refund.refund_payment") as charge,
            patch(
                "apps.billing.services.payment_refund.issue_refund_receipt"
            ) as fiscal,
        ):
            result = PaymentRefundService().refund(
                payment=payment,
                refunded_by=self.user,
                cash_shift=refund_shift,
                trusted_edge_replay=True,
                edge_operation_id="refund:" + str(uuid.uuid4()),
                refund_result={"ok": True, "provider": "local-edge"},
                fiscal_results=[self.evidence(number="refund-101")],
                occurred_at=occurred,
            )
        charge.assert_not_called()
        fiscal.assert_not_called()
        self.assertEqual(result["refund"].cash_shift_id, refund_shift.pk)
        self.assertEqual(result["refund"].refunded_at, occurred)
        self.assertEqual(
            CashShiftService().build_shift_snapshot(shift=self.shift)["refund_total"], 0
        )
        self.assertEqual(
            CashShiftService().build_shift_snapshot(shift=refund_shift)["refund_total"],
            30000,
        )

    def test_unknown_refund_gates_execution_shift_not_original_sale_shift(self):
        payment = self.pay()["payment"]
        refund_shift = self.create_cash_shift()
        PaymentRefundService().refund(
            payment=payment,
            refunded_by=self.user,
            cash_shift=refund_shift,
            trusted_edge_replay=True,
            edge_operation_id="refund:" + str(uuid.uuid4()),
            refund_result={"ok": True, "provider": "local-edge"},
            fiscal_results=[
                {"ok": False, "provider": "fiscal-drive-service", "state": "unknown"}
            ],
        )
        self.assertFalse(
            CashShiftService()
            .get_unresolved_fiscal_payments_queryset(shift=self.shift)
            .exists()
        )
        self.assertTrue(
            CashShiftService()
            .get_unresolved_fiscal_payments_queryset(shift=refund_shift)
            .exists()
        )
