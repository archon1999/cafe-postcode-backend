from rest_framework import serializers

from apps.organizations.models import CashDesk


class CashDeskSerializer(serializers.ModelSerializer):
    branch_legal_name = serializers.CharField(source='branch.legal_name', read_only=True)
    branch_tax_number = serializers.CharField(source='branch.tax_number', read_only=True)
    branch_vat_enabled = serializers.BooleanField(source='branch.vat_enabled', read_only=True)

    def validate_enabled_payment_methods(self, value):
        allowed_values = {'cash', 'card', 'qr'}
        values = list(dict.fromkeys(value or []))
        if not values:
            raise serializers.ValidationError('At least one payment method must be enabled.')
        if any(item not in allowed_values for item in values):
            raise serializers.ValidationError('Unsupported payment method selected.')
        return values

    class Meta:
        model = CashDesk
        fields = (
            'id',
            'name',
            'location',
            'branch',
            'enabled_payment_methods',
            'fiscal_provider',
            'receipt_printer_enabled',
            'terminal_id',
            'external_cashbox_id',
            'is_active',
            'branch_legal_name',
            'branch_tax_number',
            'branch_vat_enabled',
        )
