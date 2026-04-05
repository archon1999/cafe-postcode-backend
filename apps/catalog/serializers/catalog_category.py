from rest_framework import serializers

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers.mxik import MxikCodeValidationMixin


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
