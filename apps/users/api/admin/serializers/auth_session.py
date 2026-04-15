from rest_framework import serializers

class AuthSessionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    client_ip = serializers.CharField(read_only=True, allow_null=True)
    user_agent = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    revoked_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)
