import logging

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.integrations.services import charge_payment, issue_fiscal_receipt
from apps.orders.models import Order, Payment, Receipt

from .order_submission import OrderSubmissionService
from .state import OrderStateService

logger = logging.getLogger(__name__)


class OrderPaymentService:
    order_submission_service_class = OrderSubmissionService
    state_service_class = OrderStateService

    def process(self, *, order: Order, payload: dict, received_by, cash_shift=None):
        from apps.orders.serializers import PaymentSerializer

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        if order.status == Order.Status.OPEN:
            self.order_submission_service_class().submit(order)

        if cash_shift is None or cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': _('An active cashier shift is required before taking payment.')})
        if cash_shift.branch_id != order.branch_id:
            raise ValidationError({'detail': _('Active cashier shift belongs to another branch.')})

        serializer = PaymentSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data['method'] not in set(cash_shift.cash_desk.enabled_payment_methods or []):
            raise ValidationError({'method': _('Selected payment method is disabled on the active cash desk.')})

        remaining_amount = max(
            0,
            (order.total or 0)
            - (order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount')).get('total') or 0),
        )
        payment_amount = serializer.validated_data['amount']
        if remaining_amount and payment_amount < remaining_amount:
            raise ValidationError({'amount': _('Payment amount must cover the full remaining total.')})

        payment = serializer.save(order=order, received_by=received_by, cash_shift=cash_shift, cash_desk=cash_shift.cash_desk)

        payment_result = charge_payment(order=order, payment=payment)
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
