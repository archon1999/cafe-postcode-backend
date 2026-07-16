from rest_framework import serializers


class LandingLeadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    phone = serializers.CharField(max_length=40, trim_whitespace=True)
    shop = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    plan = serializers.CharField(max_length=40, required=False, allow_blank=True, trim_whitespace=True)
