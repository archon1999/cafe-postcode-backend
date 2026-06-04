from rest_framework import serializers

from django.db.models import Count, Q, Sum

from apps.billing.helpers import get_cash_shift_model, get_payment_model, get_payment_refund_model, get_receipt_model

CashShift = get_cash_shift_model()
Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()


class CashShiftSerializer(serializers.ModelSerializer):
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.full_name', read_only=True, allow_null=True)
    opened_by_name = serializers.CharField(source='opened_by.full_name', read_only=True)
    expected_closing_cash_amount = serializers.SerializerMethodField()
    cash_total = serializers.SerializerMethodField()
    card_total = serializers.SerializerMethodField()
    qr_total = serializers.SerializerMethodField()
    refund_total = serializers.SerializerMethodField()
    receipt_count = serializers.SerializerMethodField()
    reprint_count = serializers.SerializerMethodField()

    class Meta:
        model = CashShift
        fields = (
            'id',
            'cash_desk',
            'cash_desk_name',
            'cashier',
            'opened_by',
            'cashier_name',
            'opened_by_name',
            'closed_by',
            'status',
            'opened_at',
            'closed_at',
            'opening_cash_amount',
            'actual_closing_cash_amount',
            'expected_closing_cash_amount',
            'cash_difference_amount',
            'cash_total',
            'card_total',
            'qr_total',
            'refund_total',
            'receipt_count',
            'reprint_count',
            'notes_open',
            'notes_close',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_expected_closing_cash_amount(self, obj):
        return self._snapshot(obj)['expected_closing_cash_amount']

    def get_cash_total(self, obj):
        return self._snapshot(obj)['cash_total']

    def get_card_total(self, obj):
        return self._snapshot(obj)['card_total']

    def get_qr_total(self, obj):
        return self._snapshot(obj)['qr_total']

    def get_refund_total(self, obj):
        return self._snapshot(obj)['refund_total']

    def get_receipt_count(self, obj):
        return self._snapshot(obj)['receipt_count']

    def get_reprint_count(self, obj):
        return self._snapshot(obj)['reprint_count']

    def _snapshot(self, obj):
        cached = getattr(obj, '_live_snapshot', None)
        if cached is not None:
            return cached
        if obj.status != CashShift.Status.OPEN:
            cached = {
                'cash_total': obj.cash_total,
                'card_total': obj.card_total,
                'qr_total': obj.qr_total,
                'refund_total': obj.refund_total,
                'receipt_count': obj.receipt_count,
                'reprint_count': obj.reprint_count,
                'expected_closing_cash_amount': obj.expected_closing_cash_amount,
            }
            setattr(obj, '_live_snapshot', cached)
            return cached

        payments = Payment.objects.filter(cash_shift=obj, status=Payment.Status.SUCCEEDED)
        refunds = PaymentRefund.objects.filter(payment__cash_shift=obj, status=PaymentRefund.Status.SUCCEEDED)
        totals = payments.aggregate(
            cash_total=Sum('cash_amount'),
            card_total=Sum('card_amount'),
            qr_total=Sum('amount', filter=Q(method=Payment.Method.QR)),
        )
        refund_total = refunds.aggregate(total=Sum('amount')).get('total') or 0
        cash_refund_total = (
            refunds.exclude(payment__method=Payment.Method.QR).aggregate(total=Sum('payment__cash_amount')).get('total') or 0
        )
        cached = {
            'cash_total': totals.get('cash_total') or 0,
            'card_total': totals.get('card_total') or 0,
            'qr_total': totals.get('qr_total') or 0,
            'refund_total': refund_total,
            'receipt_count': Receipt.objects.filter(
                payment__cash_shift=obj,
                kind=Receipt.Kind.FISCAL,
            ).aggregate(total=Count('id')).get('total') or 0,
            'reprint_count': Receipt.objects.filter(payment__cash_shift=obj).aggregate(total=Sum('reprint_count')).get('total')
            or 0,
            'expected_closing_cash_amount': (obj.opening_cash_amount or 0)
            + (totals.get('cash_total') or 0)
            - cash_refund_total,
        }
        setattr(obj, '_live_snapshot', cached)
        return cached
