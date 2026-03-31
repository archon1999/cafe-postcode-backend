from rest_framework import serializers

from apps.catalog.models import CatalogItem


class PosCatalogItemSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    class Meta:
        model = CatalogItem
        fields = (
            'id',
            'name',
            'description',
            'prep_station',
            'prep_station_name',
            'price',
        )
