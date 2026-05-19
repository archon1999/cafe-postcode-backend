from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.billing.helpers import get_payment_model

from .payment_refund import PaymentRefundSerializer

Payment = get_payment_model()


class PaymentSerializer(serializers.ModelSerializer):
    refunds = PaymentRefundSerializer(many=True, read_only=True)
    manual_card_override = serializers.BooleanField(required=False, write_only=True, default=False)
    manual_card_reason = serializers.CharField(required=False, write_only=True, allow_blank=True, default='')
    register_fiscal = serializers.BooleanField(required=False, default=True)

    def validate_method(self, value):
        if value not in {Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR}:
            raise serializers.ValidationError(_('Only cash, card, and QR payments are supported.'))
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_('Payment amount must be greater than zero.'))
        return value

    def create(self, validated_data):
        validated_data.pop('manual_card_override', None)
        validated_data.pop('manual_card_reason', None)
        return super().create(validated_data)

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
            'register_fiscal',
            'external_ref',
            'provider_payload',
            'paid_at',
            'refunds',
            'manual_card_override',
            'manual_card_reason',
            'created_at',
        )
        read_only_fields = ('order', 'cash_desk', 'cash_shift', 'received_by', 'status', 'external_ref', 'provider_payload', 'paid_at')


class MartaTerminalResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField(required=False, default=False)
    status = serializers.CharField(required=False, allow_blank=True, default='')
    request_id = serializers.CharField(required=False, allow_blank=True, default='')
    requestId = serializers.CharField(required=False, allow_blank=True, default='')
    pid = serializers.IntegerField(required=False)
    message = serializers.CharField(required=False, allow_blank=True, default='')
    params = serializers.JSONField(required=False, default=dict)
    ac = serializers.JSONField(required=False, allow_null=True)
    debug = serializers.JSONField(required=False, default=dict)
    response = serializers.JSONField(required=False, default=dict)
    browser_error = serializers.JSONField(required=False, default=dict)
    browserError = serializers.JSONField(required=False, default=dict)
