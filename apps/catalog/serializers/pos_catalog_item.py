from rest_framework import serializers

from apps.catalog.models import CatalogItem
from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden
from apps.catalog.utils.marking import item_marking_gtin, item_requires_marking
from apps.catalog.utils.prep_station import resolve_order_item_prep_station
from apps.catalog.serializers.modifier import PosModifierGroupSerializer


class PosCatalogItemSerializer(serializers.ModelSerializer):
    menu_restaurant_context_key = 'pos_menu_restaurant'
    menu_default_prep_station_context_key = 'pos_menu_default_prep_station'

    prep_station = serializers.SerializerMethodField()
    prep_station_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    requires_marking = serializers.SerializerMethodField()
    marking_gtin = serializers.SerializerMethodField()
    mxik_code = serializers.SerializerMethodField()
    mxik_payload = serializers.SerializerMethodField()
    cash_payment_forbidden = serializers.SerializerMethodField()
    modifier_groups = serializers.SerializerMethodField()

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

    def _resolve_prep_station(self, obj):
        cache = getattr(self, '_resolved_prep_stations', None)
        if cache is None:
            cache = self._resolved_prep_stations = {}
        cache_key = id(obj)
        if cache_key in cache:
            return cache[cache_key]

        kwargs = {
            'catalog_item': obj,
            'restaurant': self.context.get(self.menu_restaurant_context_key) or obj.restaurant,
        }
        if self.menu_default_prep_station_context_key in self.context:
            kwargs['default_prep_station'] = self.context[
                self.menu_default_prep_station_context_key
            ]
        station = resolve_order_item_prep_station(**kwargs)
        cache[cache_key] = station
        return station

    def get_prep_station(self, obj):
        station = self._resolve_prep_station(obj)
        return str(station.id) if station is not None else None

    def get_prep_station_name(self, obj):
        station = self._resolve_prep_station(obj)
        return station.name if station is not None else ''

    @staticmethod
    def get_modifier_groups(obj):
        assignments = getattr(obj, 'active_modifier_assignments', None)
        if assignments is None:
            assignments = obj.modifier_assignments.filter(modifier_group__is_active=True).select_related(
                'modifier_group'
            ).prefetch_related('modifier_group__options')
        return PosModifierGroupSerializer([assignment.modifier_group for assignment in assignments], many=True).data

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
            'item_type',
            'price',
            'sale_unit',
            'modifier_groups',
        )
