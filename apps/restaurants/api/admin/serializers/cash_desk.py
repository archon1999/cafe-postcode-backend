from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.restaurants.helpers import get_cash_desk_model
from common.api.scopes import get_request_restaurant

CashDesk = get_cash_desk_model()


class CashDeskSerializer(serializers.ModelSerializer):
    fiscal_integration_name = serializers.SerializerMethodField()
    payment_integration_name = serializers.SerializerMethodField()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        restaurant = get_request_restaurant(request) if request is not None else None
        if restaurant is not None and 'fiscal_integration' in fields:
            fields['fiscal_integration'].queryset = IntegrationConfig.objects.filter(
                restaurant=restaurant,
                kind=IntegrationConfig.Kind.FISCAL,
                is_enabled=True,
            ).order_by('provider')
        if restaurant is not None and 'payment_integration' in fields:
            fields['payment_integration'].queryset = IntegrationConfig.objects.filter(
                restaurant=restaurant,
                kind=IntegrationConfig.Kind.PAYMENT,
                provider='marta-softpos',
                is_enabled=True,
            ).order_by('provider', 'created_at')
        return fields

    def validate_enabled_payment_methods(self, value):
        allowed_values = {'cash', 'card', 'qr'}
        values = list(dict.fromkeys(value or []))
        if not values:
            raise serializers.ValidationError(_('At least one payment method must be enabled.'))
        if any(item not in allowed_values for item in values):
            raise serializers.ValidationError(_('Unsupported payment method selected.'))
        return values

    def validate_fiscal_integration(self, value):
        if value is None:
            return value
        request = self.context.get('request')
        restaurant = get_request_restaurant(request) if request is not None else None
        if restaurant is not None and value.restaurant_id != restaurant.id:
            raise serializers.ValidationError(_('Selected fiscal integration belongs to another restaurant.'))
        if value.kind != IntegrationConfig.Kind.FISCAL:
            raise serializers.ValidationError(_('Selected integration is not a fiscal integration.'))
        if not value.is_enabled:
            raise serializers.ValidationError(_('Selected fiscal integration is disabled.'))
        return value

    def validate_payment_integration(self, value):
        if value is None:
            return value
        request = self.context.get('request')
        restaurant = get_request_restaurant(request) if request is not None else None
        if restaurant is not None and value.restaurant_id != restaurant.id:
            raise serializers.ValidationError(_('Selected payment integration belongs to another restaurant.'))
        if value.kind != IntegrationConfig.Kind.PAYMENT:
            raise serializers.ValidationError(_('Selected integration is not a payment integration.'))
        if value.provider != 'marta-softpos':
            raise serializers.ValidationError(_('Selected payment integration is not a MARTA SoftPOS integration.'))
        if not value.is_enabled:
            raise serializers.ValidationError(_('Selected payment integration is disabled.'))
        return value

    def get_fiscal_integration_name(self, obj):
        integration = getattr(obj, 'fiscal_integration', None)
        if integration is None:
            return ''
        settings = integration.settings or {}
        terminal_id = settings.get('terminal_id') or settings.get('terminalId') or settings.get('fiscal')
        return f'{integration.provider} ({terminal_id})' if terminal_id else integration.provider

    def get_payment_integration_name(self, obj):
        integration = getattr(obj, 'payment_integration', None)
        if integration is None:
            return ''
        settings = integration.settings or {}
        endpoint_url = settings.get('endpoint_url') or settings.get('endpointUrl')
        return f'{integration.provider} ({endpoint_url})' if endpoint_url else integration.provider

    class Meta:
        model = CashDesk
        fields = (
            'id',
            'fiscal_integration',
            'fiscal_integration_name',
            'payment_integration',
            'payment_integration_name',
            'name',
            'location',
            'enabled_payment_methods',
            'fiscal_provider',
            'receipt_printer_enabled',
            'terminal_id',
            'external_cashbox_id',
            'is_active',
        )
        read_only_fields = ('fiscal_integration_name', 'payment_integration_name')
