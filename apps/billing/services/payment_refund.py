from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_payment_refund_model, get_receipt_model
from apps.integrations.services import issue_refund_receipt, refund_payment, reprint_fiscal_receipt

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
        )
        return {'refund': refund, 'receipt': receipt}

    @transaction.atomic
    def reprint(self, *, receipt, cash_shift):
        if cash_shift is None or cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': 'An active cashier shift is required for reprint.'})
        if receipt.order.restaurant_id != cash_shift.cash_desk.restaurant_id:
            raise ValidationError({'detail': 'Receipt restaurant does not match the active cashier shift.'})

        result = reprint_fiscal_receipt(receipt=receipt)
        if result.get('ok'):
            receipt.reprint_count += 1
            receipt.last_reprinted_at = timezone.now()
            receipt.payload = {**receipt.payload, 'last_reprint': result}
            receipt.save(update_fields=['reprint_count', 'last_reprinted_at', 'payload', 'updated_at'])
        return result
