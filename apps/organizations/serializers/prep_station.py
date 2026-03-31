from rest_framework import serializers

from apps.organizations.models import PrepStation


class PrepStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrepStation
        fields = ('id', 'name', 'kind', 'is_active')
