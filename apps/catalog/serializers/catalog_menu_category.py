from rest_framework import serializers

from apps.catalog.models import CatalogCategory

from .pos_catalog_item import PosCatalogItemSerializer


class CatalogMenuCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = CatalogCategory
        fields = ('id', 'name', 'sort_order', 'items')

    def get_items(self, obj):
        prefetched_items = getattr(obj, 'active_menu_items', None)
        if prefetched_items is not None:
            return PosCatalogItemSerializer(prefetched_items, many=True).data

        item_queryset = obj.items.filter(is_active=True, is_stoplisted=False).select_related('prep_station')
        return PosCatalogItemSerializer(item_queryset, many=True).data
