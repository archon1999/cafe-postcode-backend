from rest_framework import serializers

from apps.billing.helpers import get_receipt_model

Receipt = get_receipt_model()


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = (
            'id',
            'order',
            'payment',
            'kind',
            'status',
            'provider',
            'payload',
            'reprint_count',
            'last_reprinted_at',
            'created_at',
        )
