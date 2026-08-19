from rest_framework import serializers

from apps.platform.helpers import get_tariff_model

Tariff = get_tariff_model()


class RestaurantTariffChangePreviewQuerySerializer(serializers.Serializer):
    tariff_id = serializers.PrimaryKeyRelatedField(
        source='tariff',
        queryset=Tariff.objects.filter(is_active=True),
    )


class RestaurantRoleMappingSerializer(serializers.Serializer):
    source_role_id = serializers.UUIDField(allow_null=True)
    target_role_id = serializers.UUIDField()


class RestaurantTariffChangeSerializer(serializers.Serializer):
    tariff_id = serializers.PrimaryKeyRelatedField(
        source='tariff',
        queryset=Tariff.objects.filter(is_active=True),
    )
    role_mappings = RestaurantRoleMappingSerializer(many=True, required=False, default=list)
