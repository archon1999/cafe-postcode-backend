from rest_framework import serializers


class SetupIntegrationSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=120)
    provider = serializers.CharField(max_length=120)
    settings = serializers.JSONField(required=False, default=dict)
    is_enabled = serializers.BooleanField(required=False, default=True)


class SetupCashDeskSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=255)
    location = serializers.CharField(required=False, allow_blank=True, default='')
    enabled_payment_methods = serializers.ListField(
        child=serializers.ChoiceField(choices=('cash', 'card', 'mixed')),
        allow_empty=False,
        default=['cash', 'card', 'mixed'],
    )
    receipt_printer_enabled = serializers.BooleanField(required=False, default=True)
    printer = SetupIntegrationSerializer(required=False, allow_null=True)
    payment = SetupIntegrationSerializer(required=False, allow_null=True)
    fiscal = SetupIntegrationSerializer(required=False, allow_null=True)


class SetupPrepStationSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=255)
    kind = serializers.ChoiceField(choices=('kitchen', 'bar', 'other'), default='kitchen')
    printer = SetupIntegrationSerializer(required=False, allow_null=True)


class RestaurantSetupApplySerializer(serializers.Serializer):
    preset = serializers.ChoiceField(choices=('single_terminal', 'multi_terminal'), default='single_terminal')
    cash_desks = SetupCashDeskSerializer(many=True, allow_empty=False)
    prep_stations = SetupPrepStationSerializer(many=True, allow_empty=False)
    create_takeaway = serializers.BooleanField(required=False, default=True)
    create_delivery = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        cash_names = [item['name'].strip().casefold() for item in attrs['cash_desks']]
        prep_names = [item['name'].strip().casefold() for item in attrs['prep_stations']]
        if len(cash_names) != len(set(cash_names)):
            raise serializers.ValidationError({'cash_desks': 'Cash desk names must be unique.'})
        if len(prep_names) != len(set(prep_names)):
            raise serializers.ValidationError({'prep_stations': 'Prep station names must be unique.'})
        unsupported_fiscal = [
            item['name']
            for item in attrs['cash_desks']
            if item.get('fiscal') and item['fiscal']['provider'] != 'fiscal-drive-service'
        ]
        if unsupported_fiscal:
            raise serializers.ValidationError(
                {'cash_desks': 'Fiscal Drive is the only supported fiscal provider.'}
            )
        return attrs
