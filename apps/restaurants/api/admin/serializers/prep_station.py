from rest_framework import serializers

from apps.restaurants.helpers import get_prep_station_model

PrepStation = get_prep_station_model()


class PrepStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrepStation
        fields = ('id', 'name', 'kind', 'is_active')
