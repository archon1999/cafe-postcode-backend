from rest_framework import serializers

from apps.organizations.models import FeatureConfig


class FeatureConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureConfig
        fields = (
            'id',
            'hall_enabled',
            'kitchen_enabled',
            'cashier_enabled',
            'owner_dashboard_enabled',
            'order_entry_mode',
            'kitchen_mode',
            'enabled_modules',
            'enabled_roles',
        )
