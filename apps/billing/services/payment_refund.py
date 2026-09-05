from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_payment_refund_model, get_receipt_model
from apps.integrations.services import issue_refund_receipt, refund_payment
from apps.printing.services import attach_receipt_print_document

Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()


class PaymentRefundService:
    @transaction.atomic
    def refund(self, *, payment, refunded_by, cash_shift, reason='', edge_operation_id=None,
               refund_id=None, refund_result=None, fiscal_results=None, occurred_at=None, trusted_edge_replay=False,
               manual_settlement_confirmed=False, refund_whole_order=False, refund_payments=None):
        if refund_whole_order:
            from .order_refund import refund_whole_order as execute_order_refund
            return execute_order_refund(payment=payment, refunded_by=refunded_by, cash_shift=cash_shift, reason=reason, edge_operation_id=edge_operation_id, refund_result=refund_result, fiscal_results=fiscal_results, occurred_at=occurred_at, trusted_edge_replay=trusted_edge_replay, manual_settlement_confirmed=manual_settlement_confirmed, refund_payments=refund_payments)
        payment = Payment.objects.select_for_update(of=('self',)).select_related('order', 'order__restaurant').get(pk=payment.pk)
        if edge_operation_id:
            existing = PaymentRefund.objects.filter(edge_operation_id=edge_operation_id).first()
            if existing is not None:
                if existing.payment_id != payment.pk:
                    raise ValidationError({'code': 'REFUND_IDENTITY_CONFLICT', 'detail': 'Operation belongs to a different payment.'})
                return {'refund': existing, 'receipt': payment.receipts.filter(kind=Receipt.Kind.REFUND).first()}
        if cash_shift is not None:
            cash_shift = type(cash_shift).objects.select_for_update(of=('self',)).select_related('cash_desk').get(pk=cash_shift.pk)
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': 'Only successful payments can be refunded.'})
        if payment.order.status != payment.order.Status.CLOSED:
            raise ValidationError({'detail': 'Only closed orders can be refunded.'})
        if payment.refunds.filter(status=PaymentRefund.Status.SUCCEEDED).exists():
            raise ValidationError({'code': 'REFUND_IDENTITY_CONFLICT', 'detail': 'A different operation already refunded this payment.'})
        if cash_shift is None or (cash_shift.status != cash_shift.Status.OPEN and not trusted_edge_replay):
            raise ValidationError({'detail': 'An active cashier shift is required for refunds.'})
        if payment.order.restaurant_id != cash_shift.cash_desk.restaurant_id:
            raise ValidationError({'detail': 'Payment restaurant does not match the refund shift.'})
        from .fiscal_coverage import fully_fiscalized_order_ids
        from .fiscal_evidence import fiscal_amount_minor
        covered = payment.order_id in fully_fiscalized_order_ids([payment.order_id])
        if covered:
            original_receipts = payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT)
            original_amount = sum(fiscal_amount_minor(receipt.payload or {}) for receipt in original_receipts)
            if original_amount != int(payment.amount) * 100:
                raise ValidationError({'code': 'FISCAL_REFUND_ALLOCATION_REQUIRED',
                    'detail': 'This payment is covered by an aggregate order receipt; explicit original receipt allocation is required.'})
        if not trusted_edge_replay or refund_result is None:
            from .financial_authority import FinancialAgentRequired
            raise FinancialAgentRequired()
        if not isinstance(refund_result, dict) or refund_result.get('ok') is not True:
            raise ValidationError({'code': 'REFUND_OUTCOME_UNKNOWN', 'detail': 'Confirmed refund outcome is required.'})
        if (payment.card_amount or payment.method in {Payment.Method.CARD, Payment.Method.MIXED, Payment.Method.QR}) and manual_settlement_confirmed is not True:
            raise ValidationError({'code': 'MANUAL_SETTLEMENT_REQUIRED', 'detail': 'Confirm the external card refund before recording it.'})
        if (payment.register_fiscal or covered) and not fiscal_results:
            raise ValidationError({'edgeFiscalResults': 'Fiscal refund outcome evidence is required.'})
        result_operation = refund_result.get('edgeOperationId') or refund_result.get('edge_operation_id')
        if result_operation and str(result_operation) != str(edge_operation_id):
            raise ValidationError({'code': 'REFUND_IDENTITY_CONFLICT', 'detail': 'Refund result does not match the operation.'})
        refund_result = {**refund_result, 'manualSettlementConfirmed': manual_settlement_confirmed,
                         'confirmedBy': str(refunded_by.pk), 'amount': int(payment.amount),
                         'occurredAt': (occurred_at or timezone.now()).isoformat()}
        refund = PaymentRefund.objects.create(
            **({'id': refund_id} if refund_id else {}), payment=payment, amount=payment.amount,
            reason=reason or '', refunded_by=refunded_by, status=PaymentRefund.Status.SUCCEEDED,
            external_ref=refund_result.get('reference', ''), provider_payload=refund_result,
            refunded_at=occurred_at or timezone.now(), cash_shift=cash_shift, edge_operation_id=edge_operation_id,
        )
        from .fiscal_evidence import persist_fiscal_evidence
        receipts = [persist_fiscal_evidence(payment=payment, result=result, kind=Receipt.Kind.REFUND)
                    for result in fiscal_results or []]
        receipt = receipts[0] if receipts else Receipt.objects.create(
            order=payment.order, payment=payment, kind=Receipt.Kind.REFUND,
            status=Receipt.Status.CREATED, payload={'fiscal_requested': False, 'refund_id': str(refund.pk)},
        )
        if not receipts:
            from apps.printing.services import attach_receipt_print_document
            attach_receipt_print_document(receipt=receipt, created_by=refunded_by)
        from .cash_shift import CashShiftService
        CashShiftService().record_late_financial_projection(shift=cash_shift,
            operation_id=edge_operation_id, occurred_at=refund.refunded_at)
        return {'refund': refund, 'receipt': receipt}

    @transaction.atomic
    def ensure_payment_print_document(self, *, payment, created_by, cash_shift):
        payment = (
            Payment.objects.select_for_update(of=('self',))
            .select_related('order', 'order__restaurant')
            .get(pk=payment.pk)
        )
        if cash_shift is not None:
            cash_shift = (
                type(cash_shift).objects.select_for_update(of=('self',))
                .select_related('cash_desk')
                .get(pk=cash_shift.pk)
            )
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': 'Only successful payments can be printed.'})
        if cash_shift is None or cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': 'An active cashier shift is required for printing.'})
        if payment.order.restaurant_id != cash_shift.cash_desk.restaurant_id:
            raise ValidationError({'detail': 'Payment restaurant does not match the active cashier shift.'})

        receipt = payment.receipts.order_by('-created_at').first()
        if receipt is None:
            receipt = Receipt.objects.create(
                order=payment.order,
                payment=payment,
                kind=Receipt.Kind.PLAIN,
                status=Receipt.Status.CREATED,
                provider='local-edge',
                payload={},
                original_paid_at=payment.paid_at,
            )
        self._ensure_print_document(receipt=receipt, created_by=created_by)
        return receipt

    @staticmethod
    def _ensure_print_document(*, receipt, created_by):
        return attach_receipt_print_document(
            receipt=receipt,
            fiscal_result=receipt.payload,
            created_by=created_by,
        )

    @staticmethod
    def _parse_payload_datetime(value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
