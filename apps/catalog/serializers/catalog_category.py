from rest_framework import serializers

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers.mxik import CatalogCategorySerializerMixin, MxikCodeValidationMixin


class CatalogCategorySerializer(CatalogCategorySerializerMixin, MxikCodeValidationMixin, serializers.ModelSerializer):
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
            'mxik_payload',
            'image_url',
            'image_source',
            'image_file',
            'clear_image',
            'restore_mxik_image',
            'sort_order',
            'is_active',
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
