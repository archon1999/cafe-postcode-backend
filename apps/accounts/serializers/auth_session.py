from rest_framework import serializers

from apps.accounts.models import AuthSession


class AuthSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthSession
        fields = (
            'id',
            'ui_channel',
            'status',
            'client_ip',
            'user_agent',
            'created_at',
            'revoked_at',
            'last_seen_at',
        )
        read_only_fields = fields
