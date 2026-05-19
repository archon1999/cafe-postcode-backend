from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.restaurants.helpers import get_prep_station_model
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

PrepStation = get_prep_station_model()
User = get_user_model()


class PrepStationSerializer(serializers.ModelSerializer):
    printer_integration_name = serializers.CharField(source='printer_integration.provider', read_only=True, allow_null=True)
    cook_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(),
        source='cooks',
        many=True,
        required=False,
        write_only=True,
    )
    cooks = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        restaurant = get_optional_request_restaurant(request) if request is not None else None
        if restaurant is None:
            return
        self.fields['printer_integration'].queryset = IntegrationConfig.objects.filter(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            is_enabled=True,
        )
        self.fields['cook_ids'].queryset = User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            role__code__in=('chef', 'barman', 'head_chef'),
            is_active=True,
        ).select_related('role')

    def get_cooks(self, obj):
        return [
            {'id': str(user.id), 'full_name': user.full_name, 'username': user.username}
            for user in obj.cooks.all().order_by('full_name', 'username')
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        if request is None:
            return attrs
        restaurant = get_request_restaurant(request)
        printer = attrs.get('printer_integration')
        if printer is not None and (printer.restaurant_id != restaurant.id or printer.kind != IntegrationConfig.Kind.PRINTER):
            raise serializers.ValidationError({'printer_integration': 'Selected printer integration is invalid.'})
        return attrs

    class Meta:
        model = PrepStation
        fields = (
            'id',
            'name',
            'kind',
            'printer_integration',
            'printer_integration_name',
            'cook_ids',
            'cooks',
            'is_active',
        )
