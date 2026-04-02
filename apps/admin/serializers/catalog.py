import re

from rest_framework import serializers

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.services.mxik import MxikClient, MxikError

MXIK_CODE_PATTERN = re.compile(r'^\d{17}$')


class MxikLookupResultSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    label = serializers.CharField(allow_blank=True)
    raw = serializers.JSONField(required=False)


class MxikCodeValidationMixin(serializers.Serializer):
    mxik_required = False
    sync_mxik_image = False

    def validate_mxik_code(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            if self.mxik_required and self.instance is None:
                raise serializers.ValidationError('MXIK code is required.')
            return ''
        if not MXIK_CODE_PATTERN.fullmatch(normalized_value):
            raise serializers.ValidationError('MXIK code must contain exactly 17 digits.')
        return normalized_value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        mxik_code = attrs.get('mxik_code')
        mxik_name = (attrs.get('mxik_name') or '').strip()
        existing_mxik_code = getattr(self.instance, 'mxik_code', '')
        existing_image_source = getattr(self.instance, 'image_source', '')
        existing_image_url = getattr(self.instance, 'image_url', None)
        should_sync_image = self.sync_mxik_image and bool(mxik_code) and (
            self.instance is None
            or mxik_code != existing_mxik_code
            or existing_image_source == CatalogCategory.ImageSource.MXIK_CACHE
            or not existing_image_url
        )
        lookup_result = None
        client = None

        if self.instance is not None and mxik_code is None:
            mxik_code = self.instance.mxik_code
        if self.instance is not None and not mxik_name:
            mxik_name = self.instance.mxik_name

        if self.mxik_required and not mxik_code and self.instance is None:
            raise serializers.ValidationError({'mxik_code': 'MXIK code is required.'})

        if not mxik_code:
            attrs['mxik_name'] = ''
            if self.sync_mxik_image and (self.instance is None or existing_image_source == CatalogCategory.ImageSource.MXIK_CACHE):
                attrs['image_url'] = None
                attrs['image_source'] = ''
            return attrs

        if not mxik_name or should_sync_image:
            try:
                client = MxikClient()
                lookup_result = client.lookup(mxik_code)
            except MxikError:
                lookup_result = None

        if mxik_name:
            attrs['mxik_name'] = mxik_name
        elif lookup_result is not None:
            attrs['mxik_name'] = lookup_result.get('name', '')
        else:
            attrs['mxik_name'] = mxik_name

        if should_sync_image:
            image_url = ''
            if client is not None:
                try:
                    image_url = client.get_primary_picture_url(mxik_code)
                except MxikError:
                    image_url = ''
            attrs['image_url'] = image_url or None
            attrs['image_source'] = CatalogCategory.ImageSource.MXIK_CACHE if image_url else ''

        return attrs


class CatalogCategorySerializer(MxikCodeValidationMixin, serializers.ModelSerializer):
    mxik_required = True
    sync_mxik_image = True

    class Meta:
        model = CatalogCategory
        fields = (
            'id',
            'name',
            'name_uz',
            'name_uz_crl',
            'name_ru',
            'mxik_code',
            'mxik_name',
            'image_url',
            'image_source',
            'sort_order',
            'is_active',
        )
        extra_kwargs = {
            'mxik_code': {'required': False, 'allow_blank': True},
            'mxik_name': {'required': False, 'allow_blank': True},
            'image_url': {'read_only': True},
            'image_source': {'read_only': True},
        }
        validators = []


class CatalogItemSerializer(MxikCodeValidationMixin, serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    prep_station_name = serializers.CharField(source='prep_station.name', read_only=True)

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
        }
        validators = []
