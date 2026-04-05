from rest_framework import serializers

from apps.billing.helpers import get_payment_refund_model

PaymentRefund = get_payment_refund_model()


class PaymentRefundSerializer(serializers.ModelSerializer):
    refunded_by_name = serializers.CharField(source='refunded_by.full_name', read_only=True)

    class Meta:
        model = PaymentRefund
        fields = (
            'id',
            'payment',
            'amount',
            'reason',
            'refunded_by',
            'refunded_by_name',
            'status',
            'external_ref',
            'provider_payload',
            'refunded_at',
            'created_at',
        )
        read_only_fields = (
            'payment',
            'refunded_by',
            'status',
            'external_ref',
            'provider_payload',
            'refunded_at',
            'created_at',
        )
