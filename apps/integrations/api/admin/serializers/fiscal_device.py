from rest_framework import serializers


class FiscalDeviceDiscoveryQuerySerializer(serializers.Serializer):
    endpoint_url = serializers.CharField(required=False, allow_blank=True)


class FiscalDeviceSerializer(serializers.Serializer):
    factory_id = serializers.CharField()
    terminal_id = serializers.CharField(allow_blank=True)
    reader_name = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    applet_version = serializers.CharField(allow_blank=True)
    locked = serializers.BooleanField()
    pos_locked = serializers.BooleanField()
    pos_auth = serializers.BooleanField()
    endpoint_url = serializers.CharField()
