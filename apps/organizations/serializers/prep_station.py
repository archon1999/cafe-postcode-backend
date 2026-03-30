from rest_framework import serializers

from apps.organizations.models import PrepStation


class PrepStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrepStation
        fields = ('id', 'name', 'name_uz', 'name_uz_crl', 'name_ru', 'code', 'kind', 'branch', 'is_active')
