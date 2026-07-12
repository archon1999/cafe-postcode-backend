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
    cash_amount = serializers.IntegerField(required=False, min_value=0, default=0)
    card_amount = serializers.IntegerField(required=False, min_value=0, default=0)
    edge_operation_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    edge_provider_result = serializers.JSONField(required=False, write_only=True)

    def validate_method(self, value):
        if value not in {Payment.Method.CASH, Payment.Method.CARD, Payment.Method.MIXED}:
            raise serializers.ValidationError(_('Only cash, card, and mixed payments are supported.'))
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(_('Payment amount must be greater than zero.'))
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        method = attrs.get('method')
        amount = int(attrs.get('amount') or 0)
        cash_amount = int(attrs.get('cash_amount') or 0)
        card_amount = int(attrs.get('card_amount') or 0)

        if method == Payment.Method.CASH:
            attrs['cash_amount'] = amount
            attrs['card_amount'] = 0
            return attrs
        if method == Payment.Method.CARD:
            attrs['cash_amount'] = 0
            attrs['card_amount'] = amount
            return attrs
        if method == Payment.Method.MIXED:
            if cash_amount <= 0 or card_amount <= 0:
                raise serializers.ValidationError({
                    'cash_amount': _('Mixed payment requires both cash and card amounts.'),
                    'card_amount': _('Mixed payment requires both cash and card amounts.'),
                })
            if cash_amount + card_amount != amount:
                raise serializers.ValidationError({
                    'amount': _('Cash and card amounts must equal the payment amount.'),
                })
        return attrs

    def create(self, validated_data):
        validated_data.pop('manual_card_override', None)
        validated_data.pop('manual_card_reason', None)
        validated_data.pop('edge_provider_result', None)
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
            'cash_amount',
            'card_amount',
            'fiscal_cash_amount',
            'fiscal_card_amount',
            'fiscal_adjustment_reason',
            'status',
            'register_fiscal',
            'external_ref',
            'provider_payload',
            'paid_at',
            'edge_operation_id',
            'edge_provider_result',
            'refunds',
            'manual_card_override',
            'manual_card_reason',
            'created_at',
        )
        read_only_fields = (
            'order',
            'cash_desk',
            'cash_shift',
            'received_by',
            'fiscal_cash_amount',
            'fiscal_card_amount',
            'fiscal_adjustment_reason',
            'status',
            'external_ref',
            'provider_payload',
            'paid_at',
        )


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
