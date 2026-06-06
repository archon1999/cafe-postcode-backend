from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.integrations.models import IntegrationConfig
from apps.restaurants.helpers import get_prep_station_model
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

from .printer_display import get_printer_integration_display

PrepStation = get_prep_station_model()
User = get_user_model()


class PrepStationSerializer(serializers.ModelSerializer):
    printer_integration_name = serializers.SerializerMethodField()
    cook_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(),
        source='cooks',
        many=True,
        required=False,
        write_only=True,
    )
    cooks = serializers.SerializerMethodField()

    def _allowed_cook_queryset(self):
        request = self.context.get('request')
        restaurant = get_optional_request_restaurant(request) if request is not None else None
        if restaurant is None:
            return User.objects.none()
        return User.objects.filter(
            restaurant_profile__restaurant=restaurant,
            role__code__in=('chef', 'barman', 'head_chef'),
            is_active=True,
        ).select_related('role')

    def _set_cook_queryset(self, queryset):
        field = self.fields['cook_ids']
        if hasattr(field, 'child_relation'):
            field.child_relation.queryset = queryset
            return
        field.queryset = queryset

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
        self._set_cook_queryset(self._allowed_cook_queryset())

    def to_internal_value(self, data):
        if isinstance(data, dict):
            mutable_data = data.copy()
            cook_ids = mutable_data.get('cook_ids', mutable_data.get('cookIds'))
            if isinstance(cook_ids, list):
                allowed_ids = {
                    str(user_id)
                    for user_id in self._allowed_cook_queryset()
                    .filter(id__in=[str(cook_id) for cook_id in cook_ids])
                    .values_list('id', flat=True)
                }
                mutable_data['cook_ids'] = [str(cook_id) for cook_id in cook_ids if str(cook_id) in allowed_ids]
                mutable_data.pop('cookIds', None)
                data = mutable_data
        return super().to_internal_value(data)

    def get_cooks(self, obj):
        return [
            {'id': str(user.id), 'full_name': user.full_name, 'username': user.username}
            for user in obj.cooks.all().order_by('full_name', 'username')
        ]

    def get_printer_integration_name(self, obj):
        return get_printer_integration_display(getattr(obj, 'printer_integration', None))

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
