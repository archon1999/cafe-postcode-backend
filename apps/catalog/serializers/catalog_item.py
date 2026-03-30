from rest_framework import serializers

from apps.catalog.models import CatalogItem


class CatalogItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    class Meta:
        model = CatalogItem
        fields = (
            'id',
            'branch',
            'category',
            'category_name',
            'prep_station',
            'prep_station_name',
            'name',
            'name_uz',
            'name_uz_crl',
            'name_ru',
            'mxik_code',
            'mxik_name',
            'kind',
            'description',
            'description_uz',
            'description_uz_crl',
            'description_ru',
            'sku',
            'price',
            'is_active',
            'is_stoplisted',
        )
