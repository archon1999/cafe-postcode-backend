from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.restaurants.helpers import get_distribution_point_model
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

DistributionPoint = get_distribution_point_model()


class DistributionPointSerializer(serializers.ModelSerializer):
    assigned_hall_name = serializers.CharField(source='assigned_hall.name', read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        restaurant = get_optional_request_restaurant(request) if request is not None else None
        if request is None:
            return
        if restaurant is None:
            if getattr(request.user, 'is_superuser', False):
                return
            self.fields['assigned_hall'].queryset = self.fields['assigned_hall'].queryset.none()
            return
        self.fields['assigned_hall'].queryset = self.fields['assigned_hall'].queryset.filter(
            zone_or_cabin__restaurant=restaurant,
        )

    class Meta:
        model = DistributionPoint
        fields = (
            'id',
            'name',
            'kind',
            'integration_channel',
            'assigned_hall',
            'assigned_hall_name',
            'is_active',
        )

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            if 'assigned_hall' not in exc.detail:
                raise
            detail = dict(exc.detail)
            detail.pop('assigned_hall')
            detail['assignedHall'] = [_('Invalid assigned hall.')]
            raise serializers.ValidationError(detail) from None

    def _resolve_restaurant(self, attrs):
        restaurant = attrs.get('restaurant') or getattr(self.instance, 'restaurant', None)
        if restaurant is not None:
            return restaurant

        request = self.context.get('request')
        if request is None:
            return None

        return get_request_restaurant(request)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        restaurant = self._resolve_restaurant(attrs)
        assigned_hall = attrs.get('assigned_hall', getattr(self.instance, 'assigned_hall', None))

        if assigned_hall is not None and restaurant is not None and assigned_hall.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'assignedHall': _('Selected hall does not belong to the selected restaurant.')})

        return attrs
