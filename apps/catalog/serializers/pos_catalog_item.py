from rest_framework import serializers

from apps.catalog.models import CatalogItem


class PosCatalogItemSerializer(serializers.ModelSerializer):
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)
    image_url = serializers.SerializerMethodField()

    @staticmethod
    def get_image_url(obj):
        image_file = getattr(obj, 'image_file', None)
        if obj.image_source == CatalogItem.ImageSource.MANUAL and image_file and getattr(image_file, 'name', ''):
            return image_file.url
        return obj.image_url

    class Meta:
        model = CatalogItem
        fields = (
            'id',
            'name',
            'description',
            'image_url',
            'prep_station',
            'prep_station_name',
            'price',
        )
