from rest_framework import serializers

from apps.billing.helpers import get_payment_model

Payment = get_payment_model()


class AdminPaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.IntegerField(source='order.order_number', read_only=True)
    cash_desk_name = serializers.CharField(source='cash_desk.name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.full_name', read_only=True)
    cash_shift_id = serializers.UUIDField(read_only=True)
    refunds_total = serializers.SerializerMethodField()
    is_refunded = serializers.SerializerMethodField()

    def get_refunds_total(self, obj):
        return sum(refund.amount for refund in obj.refunds.all() if refund.status == refund.Status.SUCCEEDED)

    def get_is_refunded(self, obj):
        return any(refund.status == refund.Status.SUCCEEDED for refund in obj.refunds.all())

    class Meta:
        model = Payment
        fields = (
            'id',
            'order',
            'order_number',
            'cash_desk',
            'cash_desk_name',
            'cash_shift_id',
            'received_by',
            'received_by_name',
            'method',
            'amount',
            'status',
            'external_ref',
            'provider_payload',
            'paid_at',
            'refunds_total',
            'is_refunded',
            'created_at',
            'updated_at',
        )
