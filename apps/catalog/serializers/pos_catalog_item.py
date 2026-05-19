from rest_framework import serializers

from apps.catalog.models import CatalogItem
from apps.catalog.utils.marking import item_marking_gtin, item_requires_marking


class PosCatalogItemSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    image_url = serializers.SerializerMethodField()
    requires_marking = serializers.SerializerMethodField()
    marking_gtin = serializers.SerializerMethodField()

    @staticmethod
    def get_image_url(obj):
        image_file = getattr(obj, 'image_file', None)
        if obj.image_source == CatalogItem.ImageSource.MANUAL and image_file and getattr(image_file, 'name', ''):
            return image_file.url
        return obj.image_url

    @staticmethod
    def get_requires_marking(obj):
        return item_requires_marking(obj)

    @staticmethod
    def get_marking_gtin(obj):
        return item_marking_gtin(obj)

    class Meta:
        model = CatalogItem
        fields = (
            'id',
            'name',
            'description',
            'image_url',
            'prep_station',
            'prep_station_name',
            'requires_marking',
            'marking_gtin',
            'price',
        )
