from rest_framework import serializers

from apps.orders.models import CashShift


class CashShiftSerializer(serializers.ModelSerializer):
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
    cashier_name = serializers.CharField(source='opened_by.full_name', read_only=True)

    class Meta:
        model = CashShift
        fields = (
            'id',
            'branch',
            'cash_desk',
            'cash_desk_name',
            'opened_by',
            'cashier_name',
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

