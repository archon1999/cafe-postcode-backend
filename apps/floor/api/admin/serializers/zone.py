from rest_framework import serializers

from apps.floor.models import ZoneOrCabin


class ZoneOrCabinSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZoneOrCabin
        fields = ('id', 'name', 'sort_order', 'is_active')
