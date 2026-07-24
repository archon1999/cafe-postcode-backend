from rest_framework import serializers

from django.db.models import Count, Q, Sum

from apps.billing.helpers import (
    get_cash_expense_model,
    get_cash_shift_model,
    get_payment_model,
    get_payment_refund_model,
    get_receipt_model,
)
from apps.billing.services.cash_shift_report import estimate_vat, refund_tender_amounts

CashShift = get_cash_shift_model()
CashExpense = get_cash_expense_model()
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
    expense_total = serializers.SerializerMethodField()
    sale_count = serializers.SerializerMethodField()
    refund_count = serializers.SerializerMethodField()
    total_sale_amount = serializers.SerializerMethodField()
    cash_refund_total = serializers.SerializerMethodField()
    card_refund_total = serializers.SerializerMethodField()
    qr_refund_total = serializers.SerializerMethodField()
    vat_sale_total = serializers.SerializerMethodField()
    vat_refund_total = serializers.SerializerMethodField()
    first_receipt = serializers.SerializerMethodField()
    last_receipt = serializers.SerializerMethodField()
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
            'expense_total',
            'sale_count',
            'refund_count',
            'total_sale_amount',
            'cash_refund_total',
            'card_refund_total',
            'qr_refund_total',
            'vat_sale_total',
            'vat_refund_total',
            'first_receipt',
            'last_receipt',
            'receipt_count',
            'reprint_count',
            'next_order_number',
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

    def get_expense_total(self, obj):
        return self._snapshot(obj)['expense_total']

    def get_sale_count(self, obj):
        return self._snapshot(obj)['sale_count']

    def get_refund_count(self, obj):
        return self._snapshot(obj)['refund_count']

    def get_total_sale_amount(self, obj):
        return self._snapshot(obj)['total_sale_amount']

    def get_cash_refund_total(self, obj):
        return self._snapshot(obj)['cash_refund_total']

    def get_card_refund_total(self, obj):
        return self._snapshot(obj)['card_refund_total']

    def get_qr_refund_total(self, obj):
        return self._snapshot(obj)['qr_refund_total']

    def get_vat_sale_total(self, obj):
        return self._snapshot(obj)['vat_sale_total']

    def get_vat_refund_total(self, obj):
        return self._snapshot(obj)['vat_refund_total']

    def get_first_receipt(self, obj):
        return self._snapshot(obj)['first_receipt']

    def get_last_receipt(self, obj):
        return self._snapshot(obj)['last_receipt']

    def get_receipt_count(self, obj):
        return self._snapshot(obj)['receipt_count']

    def get_reprint_count(self, obj):
        return self._snapshot(obj)['reprint_count']

    def _snapshot(self, obj):
        cached = getattr(obj, '_live_snapshot', None)
        if cached is not None:
            return cached
        payments = Payment.objects.filter(cash_shift=obj, status=Payment.Status.SUCCEEDED).select_related('order')
        refunds = list(
            PaymentRefund.objects.filter(payment__cash_shift=obj, status=PaymentRefund.Status.SUCCEEDED).select_related(
                'payment'
            )
        )
        refund_tenders = {
            Payment.Method.CASH: 0,
            Payment.Method.CARD: 0,
            Payment.Method.QR: 0,
        }
        for refund in refunds:
            for method, amount in refund_tender_amounts(refund).items():
                refund_tenders[method] = refund_tenders.get(method, 0) + int(amount or 0)
        payment_order_numbers = list(
            payments.order_by('paid_at', 'created_at').values_list('order__order_number', flat=True)
        )
        total_sale_amount = payments.aggregate(total=Sum('amount')).get('total') or 0
        refund_total = sum(int(refund.amount or 0) for refund in refunds)
        restaurant = obj.cash_desk.restaurant
        report_values = {
            'sale_count': payments.count(),
            'refund_count': len(refunds),
            'total_sale_amount': total_sale_amount,
            'cash_refund_total': refund_tenders[Payment.Method.CASH],
            'card_refund_total': refund_tenders[Payment.Method.CARD],
            'qr_refund_total': refund_tenders[Payment.Method.QR],
            'vat_sale_total': estimate_vat(total_sale_amount, restaurant=restaurant),
            'vat_refund_total': estimate_vat(refund_total, restaurant=restaurant),
            'first_receipt': str(payment_order_numbers[0]) if payment_order_numbers else '',
            'last_receipt': str(payment_order_numbers[-1]) if payment_order_numbers else '',
        }
        if obj.status != CashShift.Status.OPEN:
            cached = {
                'cash_total': obj.cash_total,
                'card_total': obj.card_total,
                'qr_total': obj.qr_total,
                'refund_total': obj.refund_total,
                'expense_total': obj.expense_total,
                'receipt_count': obj.receipt_count,
                'reprint_count': obj.reprint_count,
                'expected_closing_cash_amount': obj.expected_closing_cash_amount,
                **report_values,
            }
            setattr(obj, '_live_snapshot', cached)
            return cached

        totals = payments.aggregate(
            cash_total=Sum('cash_amount'),
            card_total=Sum('card_amount'),
            qr_total=Sum('amount', filter=Q(method=Payment.Method.QR)),
        )
        cash_refund_total = (
            refund_tenders[Payment.Method.CASH]
        )
        expense_total = (
            CashExpense.objects.filter(
                cash_shift=obj,
                status=CashExpense.Status.POSTED,
            ).aggregate(total=Sum('amount')).get('total')
            or 0
        )
        cached = {
            'cash_total': totals.get('cash_total') or 0,
            'card_total': totals.get('card_total') or 0,
            'qr_total': totals.get('qr_total') or 0,
            'refund_total': refund_total,
            'expense_total': expense_total,
            'receipt_count': Receipt.objects.filter(
                payment__cash_shift=obj,
                kind=Receipt.Kind.FISCAL,
            ).aggregate(total=Count('id')).get('total') or 0,
            'reprint_count': Receipt.objects.filter(payment__cash_shift=obj).aggregate(total=Sum('reprint_count')).get('total')
            or 0,
            'expected_closing_cash_amount': (obj.opening_cash_amount or 0)
            + (totals.get('cash_total') or 0)
            - cash_refund_total
            - expense_total,
            **report_values,
        }
        setattr(obj, '_live_snapshot', cached)
        return cached
