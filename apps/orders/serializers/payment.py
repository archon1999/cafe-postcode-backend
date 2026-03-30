from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.orders.models import Payment

from .payment_refund import PaymentRefundSerializer


class PaymentSerializer(serializers.ModelSerializer):
    refunds = PaymentRefundSerializer(many=True, read_only=True)

    def validate_method(self, value):
        if value not in {Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR}:
            raise serializers.ValidationError(_('Only cash, card, and QR payments are supported.'))
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_('Payment amount must be greater than zero.'))
        return value

    class Meta:
        model = Payment
        fields = (
            'id',
            'order',
            'cash_desk',
            'cash_shift',
            'received_by',
            'method',
            'amount',
            'status',
            'external_ref',
            'provider_payload',
            'paid_at',
            'refunds',
            'created_at',
        )
        read_only_fields = ('order', 'cash_desk', 'cash_shift', 'received_by', 'status', 'external_ref', 'provider_payload', 'paid_at')
