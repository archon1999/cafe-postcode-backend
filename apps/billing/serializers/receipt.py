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
            'print_document',
            'kind',
            'status',
            'provider',
            'split_key',
            'registration_key',
            'fiscal_session_id',
            'payload',
            'fiscal_requested_at',
            'fiscal_registered_at',
            'original_paid_at',
            'fiscal_error_code',
            'fiscal_error_message',
            'reprint_count',
            'last_reprinted_at',
            'created_at',
        )
