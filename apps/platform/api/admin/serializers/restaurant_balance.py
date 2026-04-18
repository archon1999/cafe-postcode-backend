from decimal import Decimal

from rest_framework import serializers

from apps.platform.helpers import get_restaurant_balance_transaction_model

RestaurantBalanceTransaction = get_restaurant_balance_transaction_model()


class RestaurantBalanceTransactionActorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    username = serializers.CharField()


class RestaurantBalanceTransactionSerializer(serializers.ModelSerializer):
    performed_by = serializers.SerializerMethodField()

    class Meta:
        model = RestaurantBalanceTransaction
        fields = (
            'id',
            'kind',
            'amount',
            'balance_after',
            'performed_by',
            'note',
            'period_start',
            'period_end',
            'created_at',
        )

    def get_performed_by(self, instance):
        if instance.performed_by is None:
            return None
        return RestaurantBalanceTransactionActorSerializer(instance.performed_by).data


class RestaurantBalanceTopUpSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)
