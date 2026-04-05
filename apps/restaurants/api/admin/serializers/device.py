from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.floor.models import Hall
from apps.restaurants.helpers import get_device_model
from common.api.scopes import get_request_restaurant

Device = get_device_model()


class DeviceSerializer(serializers.ModelSerializer):
    primary_hall_id = serializers.PrimaryKeyRelatedField(
        source='primary_hall',
        queryset=Hall.objects.all(),
        required=False,
        allow_null=True,
    )
    primary_hall_name = serializers.CharField(source='primary_hall.name', read_only=True)
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_halls',
        queryset=Hall.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Device
        fields = (
            'id',
            'name',
            'mode',
            'primary_hall_id',
            'primary_hall_name',
            'allowed_hall_ids',
            'is_active',
        )

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
        primary_hall = attrs.get('primary_hall', getattr(self.instance, 'primary_hall', None))

        if 'allowed_halls' in attrs:
            allowed_halls = list(attrs['allowed_halls'])
        elif self.instance:
            allowed_halls = list(self.instance.allowed_halls.all())
        else:
            allowed_halls = []

        if primary_hall is not None and restaurant is not None and primary_hall.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'primaryHallId': _('Selected hall does not belong to the selected restaurant.')})

        if restaurant is not None and any(hall.restaurant_id != restaurant.id for hall in allowed_halls):
            raise serializers.ValidationError({'allowedHallIds': _('All allowed halls must belong to the selected restaurant.')})

        if primary_hall is not None and not any(hall.id == primary_hall.id for hall in allowed_halls):
            allowed_halls.append(primary_hall)

        attrs['allowed_halls'] = allowed_halls
        return attrs

    def create(self, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', [])
        device = super().create(validated_data)
        if allowed_halls:
            device.allowed_halls.set(allowed_halls)
        return device

    def update(self, instance, validated_data):
        allowed_halls = validated_data.pop('allowed_halls', None)
        device = super().update(instance, validated_data)
        if allowed_halls is not None:
            device.allowed_halls.set(allowed_halls)
        return device
