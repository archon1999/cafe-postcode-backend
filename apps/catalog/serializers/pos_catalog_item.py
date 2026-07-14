from rest_framework import serializers

from apps.catalog.models import CatalogItem
from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden
from apps.catalog.utils.marking import item_marking_gtin, item_requires_marking
from apps.catalog.utils.prep_station import resolve_order_item_prep_station


class PosCatalogItemSerializer(serializers.ModelSerializer):
    prep_station = serializers.SerializerMethodField()
    prep_station_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    requires_marking = serializers.SerializerMethodField()
    marking_gtin = serializers.SerializerMethodField()
    mxik_code = serializers.SerializerMethodField()
    mxik_payload = serializers.SerializerMethodField()
    cash_payment_forbidden = serializers.SerializerMethodField()

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

    @staticmethod
    def get_mxik_code(obj):
        return str(obj.mxik_code or getattr(obj.category, 'mxik_code', '') or '').strip()

    @staticmethod
    def get_mxik_payload(obj):
        return obj.mxik_payload or getattr(obj.category, 'mxik_payload', {}) or {}

    @staticmethod
    def get_cash_payment_forbidden(obj):
        return is_catalog_item_cash_sale_forbidden(obj)

    @staticmethod
    def get_prep_station(obj):
        station = resolve_order_item_prep_station(catalog_item=obj, restaurant=obj.restaurant)
        return str(station.id) if station is not None else None

    @staticmethod
    def get_prep_station_name(obj):
        station = resolve_order_item_prep_station(catalog_item=obj, restaurant=obj.restaurant)
        return station.name if station is not None else ''

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
            'mxik_code',
            'mxik_payload',
            'cash_payment_forbidden',
            'price',
        )
