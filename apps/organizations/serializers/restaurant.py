from rest_framework import serializers

from apps.organizations.models import Restaurant

from .branch import BranchSerializer
from .feature_config import FeatureConfigSerializer


class RestaurantSerializer(serializers.ModelSerializer):
    feature_config = FeatureConfigSerializer(read_only=True)
    branches = BranchSerializer(many=True, read_only=True)

    class Meta:
        model = Restaurant
        fields = (
            'id',
            'name',
            'name_uz',
            'name_uz_crl',
            'name_ru',
            'legal_name',
            'legal_name_uz',
            'legal_name_uz_crl',
            'legal_name_ru',
            'tax_number',
            'phone',
            'address',
            'address_uz',
            'address_uz_crl',
            'address_ru',
            'currency',
            'feature_config',
            'branches',
        )
        extra_kwargs = {
            'currency': {'required': False},
        }

    def create(self, validated_data):
        validated_data['currency'] = 'UZS'
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['currency'] = 'UZS'
        return super().update(instance, validated_data)
