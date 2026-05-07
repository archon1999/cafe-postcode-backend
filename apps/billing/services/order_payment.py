import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.integrations.services import charge_payment, issue_fiscal_receipt
from apps.sales.helpers import get_order_model
from apps.sales.services import OrderStateService, OrderSubmissionService

logger = logging.getLogger(__name__)

Order = get_order_model()
Payment = get_payment_model()
Receipt = get_receipt_model()


class OrderPaymentService:
    order_submission_service_class = OrderSubmissionService
    state_service_class = OrderStateService

    def process(self, *, order: Order, payload: dict, received_by, cash_shift=None):
        from apps.billing.serializers import PaymentSerializer

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        if order.status == Order.Status.OPEN:
            self.order_submission_service_class().submit(order)

        if cash_shift is not None and cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': _('Only an open cashier shift can be used for payment.')})
        if cash_shift is not None and cash_shift.cash_desk.restaurant_id != order.restaurant_id:
            raise ValidationError({'detail': _('Active cashier shift belongs to another restaurant.')})

        serializer = PaymentSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        manual_card_override = bool(serializer.validated_data.pop('manual_card_override', False))
        manual_card_reason = str(serializer.validated_data.pop('manual_card_reason', '') or '')
        cash_desk = (
            cash_shift.cash_desk
            if cash_shift is not None
            else order.restaurant.cash_desks.filter(is_active=True).order_by('name').first()
        )
        if cash_desk and serializer.validated_data['method'] not in set(cash_desk.enabled_payment_methods or []):
            raise ValidationError({'method': _('Selected payment method is disabled on the active cash desk.')})

        remaining_amount = max(
            0,
            (order.total or 0)
            - (order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount')).get('total') or 0),
        )
        payment_amount = serializer.validated_data['amount']
        if remaining_amount and payment_amount < remaining_amount:
            raise ValidationError({'amount': _('Payment amount must cover the full remaining total.')})

        payment = serializer.save(order=order, received_by=received_by, cash_shift=cash_shift, cash_desk=cash_desk)

        payment_result = charge_payment(
            order=order,
            payment=payment,
            manual_card_override=manual_card_override,
            manual_card_reason=manual_card_reason,
        )
        payment.status = Payment.Status.SUCCEEDED if payment_result.get('ok') else Payment.Status.FAILED
        payment.external_ref = payment_result.get('reference', '')
        payment.provider_payload = payment_result
        payment.paid_at = timezone.now() if payment.status == Payment.Status.SUCCEEDED else None
        payment.save(update_fields=['status', 'external_ref', 'provider_payload', 'paid_at', 'updated_at'])

        if payment.status == Payment.Status.FAILED:
            logger.warning(
                'Payment charge failed',
                extra={'order_id': str(order.pk), 'payment_id': str(payment.pk), 'method': payment.method},
            )
            return {
                'payment': payment,
                'receipt': None,
                'order': order,
                'detail': payment_result.get('detail') or payment_result.get('message') or _('Payment charge failed.'),
            }

        paid_total = order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount')).get('total') or 0
        if paid_total >= order.total:
            state_service.close_order_after_payment(order=order, received_by=received_by)

        receipt_result = issue_fiscal_receipt(order=order, payment=payment)
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED,
            provider=receipt_result.get('provider', 'mock'),
            payload=receipt_result,
        )
        logger.info(
            'Payment processed',
            extra={
                'order_id': str(order.pk),
                'payment_id': str(payment.pk),
                'payment_status': payment.status,
                'receipt_status': receipt.status,
            },
        )
        return {
            'payment': payment,
            'receipt': receipt,
            'order': order,
        }


class PaymentFiscalRetryService:
    @transaction.atomic
    def retry(self, *, payment: Payment):
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': _('Only successful payments can be sent to fiscal integration.')})

        receipt = (
            payment.receipts.filter(kind=Receipt.Kind.FISCAL)
            .exclude(status=Receipt.Status.SENT)
            .order_by('-created_at')
            .first()
        )
        if receipt is None:
            receipt = payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT).order_by('-created_at').first()
        if receipt is not None and receipt.status == Receipt.Status.SENT:
            return {'payment': payment, 'receipt': receipt, 'result': receipt.payload or {}}

        receipt_result = issue_fiscal_receipt(order=payment.order, payment=payment)
        if receipt is None:
            receipt = Receipt.objects.create(
                order=payment.order,
                payment=payment,
                kind=Receipt.Kind.FISCAL,
                status=Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED,
                provider=receipt_result.get('provider', ''),
                payload=receipt_result,
            )
        else:
            receipt.status = Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED
            receipt.provider = receipt_result.get('provider', receipt.provider)
            receipt.payload = receipt_result
            receipt.save(update_fields=['status', 'provider', 'payload', 'updated_at'])
        return {'payment': payment, 'receipt': receipt, 'result': receipt_result}
