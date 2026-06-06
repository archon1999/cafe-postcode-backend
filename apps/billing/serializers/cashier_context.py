from rest_framework import serializers

from django.contrib.auth import get_user_model

from apps.restaurants.helpers import get_cash_desk_model

from .cash_shift import CashShiftSerializer

CashDesk = get_cash_desk_model()
User = get_user_model()


class CashDeskContextSerializer(serializers.ModelSerializer):
    printer_integration_name = serializers.SerializerMethodField()
    printer_integration_printer_name = serializers.SerializerMethodField()
    printer_integration_connection_type = serializers.SerializerMethodField()
    printer_integration_host = serializers.SerializerMethodField()
    printer_integration_port = serializers.SerializerMethodField()

    class Meta:
        model = CashDesk
        fields = (
            'id',
            'name',
            'location',
            'enabled_payment_methods',
            'payment_integration',
            'printer_integration',
            'printer_integration_name',
            'printer_integration_printer_name',
            'printer_integration_connection_type',
            'printer_integration_host',
            'printer_integration_port',
            'fiscal_provider',
            'receipt_printer_enabled',
            'terminal_id',
            'external_cashbox_id',
            'is_active',
        )
        read_only_fields = fields

    def get_printer_integration_name(self, obj):
        integration = getattr(obj, 'printer_integration', None)
        return getattr(integration, 'provider', None) if integration is not None else None

    def get_printer_integration_printer_name(self, obj):
        integration = getattr(obj, 'printer_integration', None)
        settings = getattr(integration, 'settings', None) if integration is not None else None
        if not isinstance(settings, dict):
            return None
        return settings.get('printer_name') or settings.get('printerName') or None

    def get_printer_integration_connection_type(self, obj):
        integration = getattr(obj, 'printer_integration', None)
        settings = getattr(integration, 'settings', None) if integration is not None else None
        if not isinstance(settings, dict):
            return None
        connection_type = settings.get('connection_type') or settings.get('connectionType')
        if connection_type:
            return connection_type
        return 'socket' if settings.get('host') else 'system_printer'

    def get_printer_integration_host(self, obj):
        integration = getattr(obj, 'printer_integration', None)
        settings = getattr(integration, 'settings', None) if integration is not None else None
        if not isinstance(settings, dict):
            return None
        return settings.get('host') or None

    def get_printer_integration_port(self, obj):
        integration = getattr(obj, 'printer_integration', None)
        settings = getattr(integration, 'settings', None) if integration is not None else None
        if not isinstance(settings, dict):
            return None
        return settings.get('port') or None


class RestaurantFiscalProfileSerializer(serializers.Serializer):
    legal_name = serializers.CharField()
    tax_number = serializers.CharField()
    service_fee_enabled = serializers.BooleanField()
    service_fee_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    vat_enabled = serializers.BooleanField()
    vat_percent = serializers.DecimalField(max_digits=5, decimal_places=2)


class CashierOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'full_name', 'username')
        read_only_fields = fields


class CashierContextSerializer(serializers.Serializer):
    restaurant_fiscal_profile = RestaurantFiscalProfileSerializer()
    available_cash_desks = CashDeskContextSerializer(many=True)
    available_cashiers = CashierOptionSerializer(many=True)
    current_shift = CashShiftSerializer(allow_null=True)
    active_shifts = CashShiftSerializer(many=True)
    fiscal_shift_open = serializers.BooleanField()


class CashShiftOpenSerializer(serializers.Serializer):
    cash_desk_id = serializers.UUIDField(required=False, allow_null=True)
    cashier_id = serializers.UUIDField(required=False, allow_null=True)
    opening_cash_amount = serializers.IntegerField(min_value=0, default=0)
    notes_open = serializers.CharField(required=False, allow_blank=True)


class CashShiftCloseSerializer(serializers.Serializer):
    cash_shift_id = serializers.UUIDField(required=False, allow_null=True)
    actual_closing_cash_amount = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    notes_close = serializers.CharField(required=False, allow_blank=True)
    close_fiscal_shift = serializers.BooleanField(required=False, default=False)


class FiscalShiftSerializer(serializers.Serializer):
    cash_desk_id = serializers.UUIDField(required=False, allow_null=True)


class PaymentRefundCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
