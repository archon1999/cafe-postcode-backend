from rest_framework import serializers

from apps.floor.models import Hall

from .dining_table import DiningTableSerializer
from .zone_or_cabin import ZoneOrCabinSerializer


class HallSerializer(serializers.ModelSerializer):
    tables = DiningTableSerializer(many=True, read_only=True)
    zone_or_cabin = ZoneOrCabinSerializer(read_only=True)
    zone_or_cabin_id = serializers.UUIDField(read_only=True)

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
