from rest_framework import serializers

class AuthSessionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    surface = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
    client_ip = serializers.CharField(read_only=True, allow_null=True)
    user_agent = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    revoked_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)
    locked_at = serializers.DateTimeField(read_only=True, allow_null=True)
    mfa_verified_at = serializers.DateTimeField(read_only=True, allow_null=True)
    refresh_family_id = serializers.UUIDField(read_only=True, allow_null=True)
    device_id = serializers.UUIDField(read_only=True, allow_null=True)
    restaurant_id = serializers.UUIDField(read_only=True, allow_null=True)
