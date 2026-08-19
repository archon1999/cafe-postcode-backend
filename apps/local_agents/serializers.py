from rest_framework import serializers

class LocalAgentStatusSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    restaurant_id = serializers.UUIDField(source='restaurant.id')
    restaurant_name = serializers.CharField(source='restaurant.name')
    name = serializers.CharField()
    status = serializers.CharField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    version = serializers.CharField()
    capabilities = serializers.JSONField()
    lan_endpoints = serializers.JSONField()
    protocol_version = serializers.IntegerField()
    rollout_state = serializers.JSONField()
