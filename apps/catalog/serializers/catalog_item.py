from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import CatalogItem
from apps.catalog.models import CatalogCategory
from apps.catalog.serializers.mxik import CatalogImageSerializerMixin, MxikCodeValidationMixin
from apps.restaurants.helpers import get_prep_station_model
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant

PrepStation = get_prep_station_model()


class CatalogItemSerializer(CatalogImageSerializerMixin, MxikCodeValidationMixin, serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return

        restaurant = get_optional_request_restaurant(request)
        if restaurant is None:
            return

        self.fields['category'].queryset = CatalogCategory.objects.filter(restaurant=restaurant)
        self.fields['prep_station'].queryset = PrepStation.objects.filter(restaurant=restaurant)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        if request is None:
            return attrs

        restaurant = get_request_restaurant(request)
        category = attrs.get('category')
        prep_station = attrs.get('prep_station')

        if category is not None and category.restaurant_id != restaurant.id:
            raise serializers.ValidationError({'category': _('Selected category does not belong to the current restaurant.')})

        if prep_station is not None and prep_station.restaurant_id != restaurant.id:
            raise serializers.ValidationError(
                {'prep_station': _('Selected prep station does not belong to the current restaurant.')}
            )

        return attrs

    class Meta:
        model = CatalogItem
        fields = (
            'id',
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
            'mxik_payload',
            'image_url',
            'image_source',
            'image_file',
            'clear_image',
            'restore_mxik_image',
            'description',
            'description_uz',
            'description_uz_crl',
            'description_ru',
            'price',
            'is_active',
            'is_stoplisted',
        )
        extra_kwargs = {
            'mxik_code': {'required': False, 'allow_blank': True},
            'mxik_name': {'required': False, 'allow_blank': True},
            'mxik_payload': {'required': False},
            'image_url': {'required': False, 'allow_null': True, 'allow_blank': True},
            'image_source': {'required': False, 'allow_blank': True},
            'image_file': {'required': False, 'allow_null': True},
        }
        validators = []
