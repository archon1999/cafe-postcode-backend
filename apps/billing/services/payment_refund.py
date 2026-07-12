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
    def refund(self, *, payment, refunded_by, cash_shift, reason=''):
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': 'Only successful payments can be refunded.'})
        if payment.order.status != payment.order.Status.CLOSED:
            raise ValidationError({'detail': 'Only closed orders can be refunded.'})
        if payment.refunds.filter(status=PaymentRefund.Status.SUCCEEDED).exists():
            raise ValidationError({'detail': 'This payment has already been refunded.'})
        if cash_shift is None or cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': 'An active cashier shift is required for refunds.'})
        if payment.order.restaurant_id != cash_shift.cash_desk.restaurant_id:
            raise ValidationError({'detail': 'Payment restaurant does not match the active cashier shift.'})

        refund_result = refund_payment(payment=payment, reason=reason)
        refund = PaymentRefund.objects.create(
            payment=payment,
            amount=payment.amount,
            reason=reason or '',
            refunded_by=refunded_by,
            status=PaymentRefund.Status.SUCCEEDED if refund_result.get('ok') else PaymentRefund.Status.FAILED,
            external_ref=refund_result.get('reference', ''),
            provider_payload=refund_result,
            refunded_at=timezone.now() if refund_result.get('ok') else None,
        )
        receipt_result = issue_refund_receipt(order=payment.order, payment=payment, refund=refund)
        receipt = Receipt.objects.create(
            order=payment.order,
            payment=payment,
            kind=Receipt.Kind.REFUND,
            status=Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED,
            provider=receipt_result.get('provider', 'mock'),
            payload=receipt_result,
            fiscal_requested_at=self._parse_payload_datetime(receipt_result.get('fiscal_requested_at')) or timezone.now(),
            fiscal_registered_at=self._parse_payload_datetime(receipt_result.get('fiscal_registered_at')) if receipt_result.get('ok') else None,
            original_paid_at=payment.paid_at,
            fiscal_error_code=str(receipt_result.get('code') or receipt_result.get('error_code') or ''),
            fiscal_error_message='' if receipt_result.get('ok') else str(receipt_result.get('detail') or receipt_result.get('message') or ''),
        )
        self._ensure_print_document(receipt=receipt, created_by=refunded_by)
        return {'refund': refund, 'receipt': receipt}

    @transaction.atomic
    def ensure_payment_print_document(self, *, payment, created_by, cash_shift):
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
