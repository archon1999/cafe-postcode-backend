from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.restaurants.helpers import get_cash_desk_model

CashDesk = get_cash_desk_model()


class CashDeskSerializer(serializers.ModelSerializer):
    def validate_enabled_payment_methods(self, value):
        allowed_values = {'cash', 'card', 'qr'}
        values = list(dict.fromkeys(value or []))
        if not values:
            raise serializers.ValidationError(_('At least one payment method must be enabled.'))
        if any(item not in allowed_values for item in values):
            raise serializers.ValidationError(_('Unsupported payment method selected.'))
        return values

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
