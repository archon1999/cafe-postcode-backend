from rest_framework import serializers


class LocalAgentEnrollmentSerializer(serializers.Serializer):
    enrollment_token = serializers.CharField(min_length=20, max_length=128, trim_whitespace=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    version = serializers.CharField(required=False, allow_blank=True, max_length=50)


class LocalAgentStatusSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    restaurant_id = serializers.UUIDField(source='restaurant.id')
    restaurant_name = serializers.CharField(source='restaurant.name')
    name = serializers.CharField()
    status = serializers.CharField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    version = serializers.CharField()
    capabilities = serializers.JSONField()
