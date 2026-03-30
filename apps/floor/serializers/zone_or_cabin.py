from rest_framework import serializers

from apps.floor.models import ZoneOrCabin


class ZoneOrCabinSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZoneOrCabin
        fields = ('id', 'hall', 'name', 'is_private', 'sort_order', 'is_active')
