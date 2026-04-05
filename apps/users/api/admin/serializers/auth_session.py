from rest_framework import serializers

from apps.users.helpers import get_auth_session_model

AuthSession = get_auth_session_model()


class AuthSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthSession
        fields = (
            'id',
            'status',
            'client_ip',
            'user_agent',
            'created_at',
            'revoked_at',
            'last_seen_at',
        )
        read_only_fields = fields
