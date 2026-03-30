from rest_framework import serializers

from apps.orders.models import Receipt


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
