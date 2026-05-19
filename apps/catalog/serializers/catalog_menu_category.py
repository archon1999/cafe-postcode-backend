from rest_framework import serializers

from apps.catalog.models import CatalogCategory
from apps.catalog.utils.cash_sale import is_catalog_category_cash_sale_forbidden

from .pos_catalog_item import PosCatalogItemSerializer


class CatalogMenuCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    cash_payment_forbidden = serializers.SerializerMethodField()

    class Meta:
        model = CatalogCategory
        fields = ('id', 'name', 'cash_payment_forbidden', 'sort_order', 'items')

    def get_cash_payment_forbidden(self, obj):
        return is_catalog_category_cash_sale_forbidden(obj)

    def get_items(self, obj):
        prefetched_items = getattr(obj, 'active_menu_items', None)
        if prefetched_items is not None:
            return PosCatalogItemSerializer(prefetched_items, many=True).data

        item_queryset = obj.items.filter(is_active=True, is_stoplisted=False).select_related('prep_station')
        return PosCatalogItemSerializer(item_queryset, many=True).data
