from rest_framework import serializers

from apps.devices.crypto import DeviceKeyError, public_key_fingerprint
from apps.devices.models import Device, DevicePairing, SecurityEvent
from apps.restaurants.models import Restaurant


class KeyProofSerializer(serializers.Serializer):
    nonce = serializers.RegexField(r'^[A-Za-z0-9_-]{22,128}$')
    signature = serializers.RegexField(r'^[A-Za-z0-9_-]{40,512}$')


class DevicePairingCreateSerializer(serializers.Serializer):
    device_type = serializers.ChoiceField(choices=Device.Type.choices)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    platform = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    app_version = serializers.CharField(max_length=50, allow_blank=True, required=False, default='')
    public_key_algorithm = serializers.ChoiceField(choices=Device.PublicKeyAlgorithm.choices)
    public_key = serializers.CharField(max_length=2048, trim_whitespace=True)
    key_proof = KeyProofSerializer()

    def validate(self, attrs):
        try:
            public_key_fingerprint(
                algorithm=attrs['public_key_algorithm'],
                public_key=attrs['public_key'],
            )
        except DeviceKeyError as error:
            raise serializers.ValidationError({'publicKey': str(error)}) from error
        return attrs


class DevicePairingStatusSerializer(serializers.Serializer):
    poll_token = serializers.CharField(min_length=32, max_length=128, trim_whitespace=True)
    timestamp = serializers.IntegerField(min_value=1)
    nonce = serializers.RegexField(r'^[A-Za-z0-9_-]{22,128}$')
    signature = serializers.RegexField(r'^[A-Za-z0-9_-]{40,512}$')


class DeviceSerializer(serializers.ModelSerializer):
    restaurant_id = serializers.UUIDField(read_only=True, allow_null=True)
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True, allow_null=True)

    class Meta:
        model = Device
        fields = (
            'id',
            'restaurant_id',
            'restaurant_name',
            'type',
            'name',
            'platform',
            'app_version',
            'public_key_algorithm',
            'public_key_fingerprint',
            'status',
            'capabilities',
            'paired_at',
            'lease_expires_at',
            'last_seen_at',
            'revoked_at',
            'revoke_reason',
            'created_at',
        )


class DevicePairingAdminSerializer(serializers.ModelSerializer):
    device = DeviceSerializer(read_only=True)

    class Meta:
        model = DevicePairing
        fields = (
            'id',
            'device_type',
            'requested_name',
            'platform',
            'app_version',
            'public_key_algorithm',
            'public_key_fingerprint',
            'display_code',
            'status',
            'expires_at',
            'approved_at',
            'rejected_at',
            'device',
            'created_at',
        )


class PairingDecisionSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128)
    restaurant_id = serializers.PrimaryKeyRelatedField(
        source='restaurant',
        queryset=Restaurant.objects.filter(is_active=True),
        allow_null=True,
        required=False,
        default=None,
    )
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class PairingRejectSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128)


class DeviceRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=500)


class SecurityEventSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True, allow_null=True)
    actor_name = serializers.CharField(source='actor.full_name', read_only=True, allow_null=True)

    class Meta:
        model = SecurityEvent
        fields = (
            'id',
            'created_at',
            'event_type',
            'severity',
            'restaurant_id',
            'restaurant_name',
            'actor_id',
            'actor_name',
            'device_id',
            'auth_session_id',
            'request_id',
            'client_ip',
            'result',
            'metadata',
            'acknowledged_at',
            'acknowledged_by_id',
        )
