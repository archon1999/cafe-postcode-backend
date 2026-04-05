from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.sales.helpers import get_order_item_model

OrderItem = get_order_item_model()


class OrderItemSerializer(serializers.ModelSerializer):
    catalog_item_name = serializers.CharField(source='catalog_item.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    class Meta:
        model = OrderItem
        fields = (
            'id',
            'order',
            'catalog_item',
            'catalog_item_name',
            'prep_station',
            'prep_station_name',
            'quantity',
            'unit_price',
            'line_total',
            'status',
            'note',
            'created_at',
        )
        read_only_fields = ('order', 'unit_price', 'line_total', 'prep_station')

    def validate(self, attrs):
        catalog_item = attrs.get('catalog_item') or getattr(self.instance, 'catalog_item', None)
        if catalog_item and not catalog_item.is_active:
            raise serializers.ValidationError({'catalog_item': _('This menu item is inactive.')})
        if catalog_item and catalog_item.is_stoplisted:
            raise serializers.ValidationError({'catalog_item': _('This menu item is in stoplist.')})
        return attrs

    def create(self, validated_data):
        catalog_item = validated_data['catalog_item']
        validated_data['unit_price'] = int(catalog_item.price or 0)
        validated_data['prep_station'] = catalog_item.prep_station
        return super().create(validated_data)
