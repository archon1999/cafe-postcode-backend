from rest_framework import serializers

from apps.floor.models import Hall, ZoneOrCabin
from common.api.scopes import get_request_restaurant

from .table import DiningTableSerializer
from .zone import ZoneOrCabinSerializer


class HallSerializer(serializers.ModelSerializer):
    zone_or_cabin_id = serializers.PrimaryKeyRelatedField(source='zone_or_cabin', queryset=ZoneOrCabin.objects.all())
    zone_or_cabin = ZoneOrCabinSerializer(read_only=True)
    tables = DiningTableSerializer(many=True, read_only=True)

    class Meta:
        model = Hall
        fields = (
            'id',
            'name',
            'description',
            'grid_columns',
            'sort_order',
            'is_active',
            'zone_or_cabin_id',
            'zone_or_cabin',
            'tables',
        )
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        restaurant = get_request_restaurant(request) if request is not None else getattr(self.instance, 'restaurant', None)
        zone_or_cabin = attrs.get('zone_or_cabin', getattr(self.instance, 'zone_or_cabin', None))

        if zone_or_cabin is not None and restaurant is not None and zone_or_cabin.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'zoneOrCabinId': 'Selected zone does not belong to the current restaurant.'})

        if self.instance is not None and zone_or_cabin is not None and self.instance.tables.exclude(zone=zone_or_cabin).exists():
            raise serializers.ValidationError({'zoneOrCabinId': 'Reassign or remove tables before changing the zone or cabin.'})

        return attrs

    def update(self, instance, validated_data):
        hall = super().update(instance, validated_data)
        hall.tables.exclude(zone=hall.zone_or_cabin).update(zone=hall.zone_or_cabin)
        return hall
