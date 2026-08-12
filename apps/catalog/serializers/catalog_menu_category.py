from rest_framework import serializers

from apps.catalog.models import CatalogCategory
from apps.catalog.utils.cash_sale import is_catalog_category_cash_sale_forbidden

from .pos_catalog_item import PosCatalogItemSerializer
from .catalog_item_group import PosCatalogItemGroupSerializer


class CatalogMenuCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    item_groups = serializers.SerializerMethodField()
    cash_payment_forbidden = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    class Meta:
        model = CatalogCategory
        fields = (
            'id',
            'name',
            'image_url',
            'prep_station',
            'prep_station_name',
            'cash_payment_forbidden',
            'sort_order',
            'items',
            'item_groups',
        )

    def get_cash_payment_forbidden(self, obj):
        return is_catalog_category_cash_sale_forbidden(obj)

    @staticmethod
    def get_image_url(obj):
        image_file = getattr(obj, 'image_file', None)
        if obj.image_source == CatalogCategory.ImageSource.MANUAL and image_file and getattr(image_file, 'name', ''):
            return image_file.url
        return obj.image_url

    def get_items(self, obj):
        prefetched_items = getattr(obj, 'active_menu_items', None)
        if prefetched_items is not None:
            return PosCatalogItemSerializer(
                prefetched_items,
                many=True,
                context=self.context,
            ).data

        item_queryset = obj.items.filter(is_active=True, is_stoplisted=False).select_related(
            'category__prep_station',
            'prep_station',
        )
        return PosCatalogItemSerializer(
            item_queryset,
            many=True,
            context=self.context,
        ).data

    def get_item_groups(self, obj):
        prefetched_groups = getattr(obj, 'active_item_groups', None)
        if prefetched_groups is None:
            prefetched_groups = obj.item_groups.filter(is_active=True).prefetch_related(
                'members__catalog_item'
            )
        return PosCatalogItemGroupSerializer(
            prefetched_groups,
            many=True,
            context=self.context,
        ).data
