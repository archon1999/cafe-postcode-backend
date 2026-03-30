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

    def validate_mxik_code(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            if self.mxik_required:
                raise serializers.ValidationError('MXIK code is required.')
            return ''
        if not MXIK_CODE_PATTERN.fullmatch(normalized_value):
            raise serializers.ValidationError('MXIK code must contain exactly 17 digits.')
        return normalized_value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        mxik_code = attrs.get('mxik_code')
        mxik_name = (attrs.get('mxik_name') or '').strip()

        if self.instance is not None and mxik_code is None:
            mxik_code = self.instance.mxik_code
        if self.instance is not None and not mxik_name:
            mxik_name = self.instance.mxik_name

        if self.mxik_required and not mxik_code:
            raise serializers.ValidationError({'mxik_code': 'MXIK code is required.'})

        if not mxik_code:
            attrs['mxik_name'] = ''
            return attrs

        if mxik_name:
            attrs['mxik_name'] = mxik_name
            return attrs

        try:
            attrs['mxik_name'] = MxikClient().lookup(mxik_code).get('name', '')
        except MxikError:
            attrs['mxik_name'] = mxik_name
        return attrs


class CatalogCategorySerializer(MxikCodeValidationMixin, serializers.ModelSerializer):
    mxik_required = True

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
            'sort_order',
            'is_active',
        )
        extra_kwargs = {
            'mxik_code': {'required': True, 'allow_blank': False},
            'mxik_name': {'required': False, 'allow_blank': True},
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
