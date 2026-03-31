from rest_framework import serializers

from apps.floor.models import Hall
from apps.organizations.models import Device


class DeviceSerializer(serializers.ModelSerializer):
    primary_hall_id = serializers.PrimaryKeyRelatedField(
        source='primary_hall',
        queryset=Hall.objects.all(),
        required=False,
        allow_null=True,
    )
    allowed_hall_ids = serializers.PrimaryKeyRelatedField(
        source='allowed_halls',
        queryset=Hall.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Device
        fields = ('id', 'name', 'mode', 'primary_hall_id', 'allowed_hall_ids', 'is_active')
