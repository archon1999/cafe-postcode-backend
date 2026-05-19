import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.integrations.services import charge_payment, issue_fiscal_receipts
from apps.sales.helpers import get_order_model
from apps.sales.services import OrderStateService, OrderSubmissionService
from common.api.permissions import POS_FISCAL_RECEIPTS_SKIP_PERMISSION, has_permission_code

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

        if cash_shift is None:
            raise ValidationError({'detail': _('Open a cashier shift before accepting payments.')})
        if cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError({'detail': _('Only an open cashier shift can be used for payment.')})
        if cash_shift.cash_desk.restaurant_id != order.restaurant_id:
            raise ValidationError({'detail': _('Active cashier shift belongs to another restaurant.')})

        serializer = PaymentSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        manual_card_override = bool(serializer.validated_data.pop('manual_card_override', False))
        manual_card_reason = str(serializer.validated_data.pop('manual_card_reason', '') or '')
        register_fiscal = bool(serializer.validated_data.get('register_fiscal', True))
        if not register_fiscal and not has_permission_code(received_by, POS_FISCAL_RECEIPTS_SKIP_PERMISSION):
            raise ValidationError({'register_fiscal': _('You do not have permission to skip fiscal registration.')})
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

        receipts = []
        if payment.register_fiscal:
            for receipt_result in issue_fiscal_receipts(order=order, payment=payment):
                receipts.append(self._create_fiscal_receipt(order=order, payment=payment, receipt_result=receipt_result))
        logger.info(
            'Payment processed',
            extra={
                'order_id': str(order.pk),
                'payment_id': str(payment.pk),
                'payment_status': payment.status,
                'receipt_count': len(receipts),
            },
        )
        return {
            'payment': payment,
            'receipt': receipts[0] if receipts else None,
            'receipts': receipts,
            'order': order,
        }

    def _create_fiscal_receipt(self, *, order, payment, receipt_result: dict):
        status = Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED
        return Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=status,
            provider=receipt_result.get('provider', ''),
            payload=receipt_result,
            fiscal_requested_at=self._parse_payload_datetime(receipt_result.get('fiscal_requested_at')) or timezone.now(),
            fiscal_registered_at=self._parse_payload_datetime(receipt_result.get('fiscal_registered_at')) if status == Receipt.Status.SENT else None,
            original_paid_at=payment.paid_at,
            fiscal_error_code=str(receipt_result.get('code') or receipt_result.get('error_code') or ''),
            fiscal_error_message='' if status == Receipt.Status.SENT else str(receipt_result.get('detail') or receipt_result.get('message') or ''),
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


class PaymentFiscalRetryService:
    @transaction.atomic
    def retry(self, *, payment: Payment):
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError({'detail': _('Only successful payments can be sent to fiscal integration.')})

        if not payment.register_fiscal:
            raise ValidationError({'detail': _('This payment was marked to skip fiscal registration.')})

        sent_receipts = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT).order_by('created_at')
        )
        pending_receipts = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL)
            .exclude(status=Receipt.Status.SENT)
            .order_by('created_at')
        )
        if sent_receipts and not pending_receipts:
            return {
                'payment': payment,
                'receipt': sent_receipts[0],
                'receipts': sent_receipts,
                'result': sent_receipts[0].payload or {},
                'results': [receipt.payload or {} for receipt in sent_receipts],
            }

        split_reasons = self._retry_split_reasons(sent_receipts=sent_receipts, pending_receipts=pending_receipts)
        receipts = []
        results = issue_fiscal_receipts(order=payment.order, payment=payment, split_reasons=split_reasons)
        for index, receipt_result in enumerate(results):
            receipt = self._pick_existing_receipt(
                pending_receipts=pending_receipts,
                split_reason=str(receipt_result.get('split_reason') or ''),
                fallback_index=index,
            )
            receipts.append(self._persist_result(payment=payment, receipt=receipt, receipt_result=receipt_result))

        return {
            'payment': payment,
            'receipt': receipts[0] if receipts else None,
            'receipts': receipts,
            'result': results[0] if results else {},
            'results': results,
        }

    def _retry_split_reasons(self, *, sent_receipts: list[Receipt], pending_receipts: list[Receipt]):
        if not sent_receipts:
            return None
        split_reasons = [
            str((receipt.payload or {}).get('split_reason') or '')
            for receipt in pending_receipts
            if str((receipt.payload or {}).get('split_reason') or '')
        ]
        if split_reasons:
            return list(dict.fromkeys(split_reasons))
        raise ValidationError({
            'detail': _(
                'This payment has partially registered fiscal receipts, but failed receipt split metadata is missing. '
                'Retry is blocked to avoid duplicate fiscal registration.'
            )
        })

    def _pick_existing_receipt(self, *, pending_receipts: list[Receipt], split_reason: str, fallback_index: int):
        for receipt in pending_receipts:
            payload = receipt.payload or {}
            if str(payload.get('split_reason') or '') == split_reason:
                pending_receipts.remove(receipt)
                return receipt
        if fallback_index < len(pending_receipts):
            return pending_receipts.pop(fallback_index)
        if pending_receipts:
            return pending_receipts.pop(0)
        return None

    def _persist_result(self, *, payment: Payment, receipt, receipt_result: dict):
        status = Receipt.Status.SENT if receipt_result.get('ok') else Receipt.Status.FAILED
        values = {
            'status': status,
            'provider': receipt_result.get('provider', ''),
            'payload': receipt_result,
            'fiscal_requested_at': OrderPaymentService._parse_payload_datetime(receipt_result.get('fiscal_requested_at')) or timezone.now(),
            'fiscal_registered_at': OrderPaymentService._parse_payload_datetime(receipt_result.get('fiscal_registered_at')) if status == Receipt.Status.SENT else None,
            'original_paid_at': payment.paid_at,
            'fiscal_error_code': str(receipt_result.get('code') or receipt_result.get('error_code') or ''),
            'fiscal_error_message': '' if status == Receipt.Status.SENT else str(receipt_result.get('detail') or receipt_result.get('message') or ''),
        }
        if receipt is None:
            return Receipt.objects.create(
                order=payment.order,
                payment=payment,
                kind=Receipt.Kind.FISCAL,
                **values,
            )

        for field, value in values.items():
            setattr(receipt, field, value)
        receipt.save(
            update_fields=[
                'status',
                'provider',
                'payload',
                'fiscal_requested_at',
                'fiscal_registered_at',
                'original_paid_at',
                'fiscal_error_code',
                'fiscal_error_message',
                'updated_at',
            ]
        )
        return receipt
