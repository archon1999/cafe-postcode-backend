from rest_framework import serializers

from apps.billing.helpers import get_receipt_model

Receipt = get_receipt_model()


class AdminReceiptSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    payment_method = serializers.CharField(source='payment.method', read_only=True)
    payment_amount = serializers.IntegerField(source='payment.amount', read_only=True)

    class Meta:
        model = Receipt
        fields = (
            'id',
            'order',
            'order_number',
            'payment',
            'payment_method',
            'payment_amount',
            'kind',
            'status',
            'provider',
            'payload',
            'reprint_count',
            'last_reprinted_at',
            'created_at',
            'updated_at',
        )
