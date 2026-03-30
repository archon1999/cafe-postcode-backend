from rest_framework import serializers

from apps.catalog.models import CatalogCategory


class CatalogCategorySerializer(serializers.ModelSerializer):
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

    def validate(self, attrs):
        mxik_code = (attrs.get('mxik_code') or getattr(self.instance, 'mxik_code', '')).strip()
        if not mxik_code:
            raise serializers.ValidationError({'mxik_code': 'MXIK code is required.'})
        return attrs
