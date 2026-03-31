from rest_framework import serializers

from apps.orders.serializers.cash_shift import CashShiftSerializer
from apps.organizations.models import CashDesk


class CashDeskContextSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashDesk
        fields = (
            'id',
            'name',
            'location',
            'enabled_payment_methods',
            'fiscal_provider',
            'receipt_printer_enabled',
            'terminal_id',
            'external_cashbox_id',
            'is_active',
        )
        read_only_fields = fields


class RestaurantFiscalProfileSerializer(serializers.Serializer):
    legal_name = serializers.CharField()
    tax_number = serializers.CharField()
    vat_enabled = serializers.BooleanField()


class CashierContextSerializer(serializers.Serializer):
    restaurant_fiscal_profile = RestaurantFiscalProfileSerializer()
    available_cash_desks = CashDeskContextSerializer(many=True)
    current_shift = CashShiftSerializer(allow_null=True)


class CashShiftOpenSerializer(serializers.Serializer):
    cash_desk_id = serializers.UUIDField(required=False, allow_null=True)
    opening_cash_amount = serializers.IntegerField(min_value=0, default=0)
    notes_open = serializers.CharField(required=False, allow_blank=True)


class CashShiftCloseSerializer(serializers.Serializer):
    actual_closing_cash_amount = serializers.IntegerField(min_value=0)
    notes_close = serializers.CharField(required=False, allow_blank=True)


class PaymentRefundCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
