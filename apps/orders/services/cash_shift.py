from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.orders.models import CashShift, Payment, PaymentRefund, Receipt
from apps.organizations.models import CashDesk


class CashShiftService:
    def get_active_shift(self, *, restaurant, user):
        return (
            CashShift.objects.select_related('cash_desk', 'opened_by')
            .filter(cash_desk__restaurant=restaurant, opened_by=user, status=CashShift.Status.OPEN)
            .order_by('-opened_at')
            .first()
        )

    def get_available_cash_desks(self, *, restaurant):
        return list(CashDesk.objects.filter(restaurant=restaurant, is_active=True).order_by('name'))

    def build_context(self, *, restaurant, user):
        active_shift = self.get_active_shift(restaurant=restaurant, user=user)
        return {
            'restaurant_fiscal_profile': {
                'legal_name': restaurant.legal_name,
                'tax_number': restaurant.tax_number,
                'vat_enabled': False,
            },
            'available_cash_desks': self.get_available_cash_desks(restaurant=restaurant),
            'current_shift': active_shift,
        }

    @transaction.atomic
    def open_shift(self, *, restaurant, cash_desk, opened_by, opening_cash_amount=0, notes_open=''):
        if cash_desk.restaurant_id != restaurant.id:
            raise ValidationError({'cashDeskId': 'Selected cash desk does not belong to the current restaurant.'})
        if not cash_desk.is_active:
            raise ValidationError({'cashDeskId': 'Selected cash desk is inactive.'})
        if CashShift.objects.filter(cash_desk__restaurant=restaurant, opened_by=opened_by, status=CashShift.Status.OPEN).exists():
            raise ValidationError({'detail': 'Current user already has an open cashier shift.'})
        if CashShift.objects.filter(cash_desk=cash_desk, status=CashShift.Status.OPEN).exists():
            raise ValidationError({'cashDeskId': 'Selected cash desk already has an active shift.'})

        shift = CashShift.objects.create(
            cash_desk=cash_desk,
            opened_by=opened_by,
            opened_at=timezone.now(),
            opening_cash_amount=max(0, opening_cash_amount or 0),
            notes_open=notes_open or '',
        )
        return shift

    def build_shift_snapshot(self, *, shift):
        payments = shift.payments.filter(status=Payment.Status.SUCCEEDED)
        refunds = PaymentRefund.objects.filter(payment__cash_shift=shift, status=PaymentRefund.Status.SUCCEEDED)
        receipts = Receipt.objects.filter(payment__cash_shift=shift)

        payment_totals = payments.values('method').annotate(total=Sum('amount'))
        totals = {item['method']: item['total'] or 0 for item in payment_totals}

        refund_total = refunds.aggregate(total=Sum('amount')).get('total') or 0
        cash_refund_total = (
            refunds.filter(payment__method=Payment.Method.CASH).aggregate(total=Sum('amount')).get('total') or 0
        )

        return {
            'cash_total': totals.get(Payment.Method.CASH, 0),
            'card_total': totals.get(Payment.Method.CARD, 0),
            'qr_total': totals.get(Payment.Method.QR, 0),
            'refund_total': refund_total,
            'receipt_count': receipts.filter(kind=Receipt.Kind.FISCAL).aggregate(total=Count('id')).get('total') or 0,
            'reprint_count': receipts.aggregate(total=Sum('reprint_count')).get('total') or 0,
            'expected_closing_cash_amount': (shift.opening_cash_amount or 0)
            + totals.get(Payment.Method.CASH, 0)
            - cash_refund_total,
        }

    @transaction.atomic
    def close_shift(self, *, shift, actual_closing_cash_amount, closed_by, notes_close=''):
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({'detail': 'Only open shifts can be closed.'})

        snapshot = self.build_shift_snapshot(shift=shift)
        actual = max(0, actual_closing_cash_amount or 0)
        expected = snapshot['expected_closing_cash_amount']
        shift.status = CashShift.Status.CLOSED
        shift.closed_by = closed_by
        shift.closed_at = timezone.now()
        shift.actual_closing_cash_amount = actual
        shift.expected_closing_cash_amount = expected
        shift.cash_difference_amount = actual - expected
        shift.cash_total = snapshot['cash_total']
        shift.card_total = snapshot['card_total']
        shift.qr_total = snapshot['qr_total']
        shift.refund_total = snapshot['refund_total']
        shift.receipt_count = snapshot['receipt_count']
        shift.reprint_count = snapshot['reprint_count']
        shift.notes_close = notes_close or ''
        shift.save(
            update_fields=[
                'status',
                'closed_by',
                'closed_at',
                'actual_closing_cash_amount',
                'expected_closing_cash_amount',
                'cash_difference_amount',
                'cash_total',
                'card_total',
                'qr_total',
                'refund_total',
                'receipt_count',
                'reprint_count',
                'notes_close',
                'updated_at',
            ]
        )
        return shift
