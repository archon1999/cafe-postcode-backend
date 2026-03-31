from rest_framework import serializers

from apps.organizations.models import DistributionPoint


class DistributionPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistributionPoint
        fields = (
            'id',
            'name',
            'name_uz',
            'name_uz_crl',
            'name_ru',
            'kind',
            'integration_channel',
            'assigned_hall',
            'is_active',
        )
