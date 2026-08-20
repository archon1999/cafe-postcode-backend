from rest_framework import serializers

from apps.devices.models import Device, DevicePairing
from apps.telegram_reports.models import TelegramBranchSubscription


CONTROL_DEVICE_TYPES = (
    Device.Type.POS_TERMINAL,
    Device.Type.LOCAL_AGENT,
    Device.Type.TV_MONITOR,
)


def masked_fingerprint(value: str) -> str:
    fingerprint = str(value or '')
    if not fingerprint:
        return ''
    if len(fingerprint) <= 12:
        return '•' * len(fingerprint)
    return f'{fingerprint[:6]}…{fingerprint[-6:]}'


class ControlBranchSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    active_device_count = serializers.IntegerField(read_only=True)
    revoked_device_count = serializers.IntegerField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)


class ControlDeviceSerializer(serializers.ModelSerializer):
    fingerprint_hint = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = (
            'id',
            'type',
            'name',
            'platform',
            'app_version',
            'status',
            'last_seen_at',
            'paired_at',
            'revoked_at',
            'revoke_reason',
            'fingerprint_hint',
        )
        read_only_fields = fields

    def get_fingerprint_hint(self, obj):
        return masked_fingerprint(obj.public_key_fingerprint)


class ControlResolvedPairingSerializer(serializers.ModelSerializer):
    fingerprint_hint = serializers.SerializerMethodField()
    display_code_length = serializers.SerializerMethodField()

    class Meta:
        model = DevicePairing
        fields = (
            'id',
            'device_type',
            'requested_name',
            'platform',
            'app_version',
            'expires_at',
            'fingerprint_hint',
            'display_code_length',
        )
        read_only_fields = fields

    def get_fingerprint_hint(self, obj):
        return masked_fingerprint(obj.public_key_fingerprint)

    def get_display_code_length(self, obj):
        return 6


class ControlPairingResolveSerializer(serializers.Serializer):
    pairing_id = serializers.UUIDField()
    claim_token = serializers.CharField(min_length=32, max_length=128, trim_whitespace=False)


class ControlPairingDecisionSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128, trim_whitespace=False)
    display_code = serializers.RegexField(r'^\d{6}$', trim_whitespace=False)
    name = serializers.CharField(max_length=255, trim_whitespace=True, required=False, allow_blank=True, default='')


class ControlPairingRejectSerializer(serializers.Serializer):
    claim_token = serializers.CharField(min_length=32, max_length=128, trim_whitespace=False)
    display_code = serializers.RegexField(r'^\d{6}$', trim_whitespace=False)


class ControlDeviceRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=500, trim_whitespace=True)


class ControlTelegramSubscriptionSerializer(serializers.ModelSerializer):
    telegram_user_id = serializers.CharField(source='account.telegram_user_id', read_only=True)
    username = serializers.CharField(source='account.username', read_only=True)
    first_name = serializers.CharField(source='account.first_name', read_only=True)
    notifications_enabled = serializers.BooleanField(source='account.notifications_enabled', read_only=True)
    linked_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = TelegramBranchSubscription
        fields = (
            'id',
            'telegram_user_id',
            'username',
            'first_name',
            'notifications_enabled',
            'linked_at',
        )
        read_only_fields = fields
