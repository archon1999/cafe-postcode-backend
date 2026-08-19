import hashlib

from django.conf import settings
from django.db import models

from common.models import BaseModel


def hash_device_secret(value: str) -> str:
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


class Device(BaseModel):
    class Type(models.TextChoices):
        POS_TERMINAL = 'POS_TERMINAL', 'POS terminal'
        LOCAL_AGENT = 'LOCAL_AGENT', 'Local Agent'
        TV_MONITOR = 'TV_MONITOR', 'TV monitor'
        CONTROL_DEVICE = 'CONTROL_DEVICE', 'Control device'

    class PublicKeyAlgorithm(models.TextChoices):
        ED25519 = 'ED25519', 'Ed25519'
        P256_SHA256 = 'P256_SHA256', 'ECDSA P-256 SHA-256'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        REVOKED = 'REVOKED', 'Revoked'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='devices',
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    public_key_algorithm = models.CharField(max_length=32, choices=PublicKeyAlgorithm.choices)
    public_key = models.TextField()
    public_key_fingerprint = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    capabilities = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Populated only by the bounded Local-Agent-attested POS migration.
    # The digest prevents one legacy Edge terminal credential from silently
    # creating multiple server devices while keeping the terminal ID private.
    legacy_migration_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    paired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='paired_devices',
        null=True,
        blank=True,
    )
    paired_at = models.DateTimeField()
    lease_expires_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='revoked_devices',
        null=True,
        blank=True,
    )
    revoke_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ('restaurant__name', 'type', 'name')
        indexes = [
            models.Index(fields=['restaurant', 'type', 'status'], name='device_rest_type_status_idx'),
            models.Index(fields=['status', 'last_seen_at'], name='device_status_seen_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(type='CONTROL_DEVICE')
                    | models.Q(restaurant__isnull=False)
                ),
                name='device_restaurant_required',
            ),
            models.UniqueConstraint(
                fields=['restaurant'],
                condition=models.Q(type='LOCAL_AGENT', status='ACTIVE'),
                name='one_active_agent_device_per_restaurant',
            ),
        ]

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE and self.revoked_at is None

    def __str__(self):
        return f'{self.type}:{self.restaurant_id or "platform"}:{self.name}'


class DevicePairing(BaseModel):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        EXPIRED = 'EXPIRED', 'Expired'

    device_type = models.CharField(max_length=32, choices=Device.Type.choices)
    requested_name = models.CharField(max_length=255)
    platform = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    public_key_algorithm = models.CharField(max_length=32, choices=Device.PublicKeyAlgorithm.choices)
    public_key = models.TextField()
    public_key_fingerprint = models.CharField(max_length=64, db_index=True)
    poll_token_hash = models.CharField(max_length=64, unique=True)
    claim_token_hash = models.CharField(max_length=64, unique=True)
    display_code = models.CharField(max_length=6)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='approved_device_pairings',
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='rejected_device_pairings',
        null=True,
        blank=True,
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    device = models.OneToOneField(
        Device,
        on_delete=models.SET_NULL,
        related_name='pairing',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['status', 'expires_at'], name='device_pair_status_exp_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['public_key_fingerprint'],
                condition=models.Q(status='PENDING'),
                name='one_pending_pairing_per_device_key',
            ),
        ]


class SecurityEvent(BaseModel):
    class Severity(models.TextChoices):
        INFO = 'INFO', 'Info'
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    event_type = models.CharField(max_length=80, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO, db_index=True)
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.SET_NULL,
        related_name='security_events',
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='security_events',
        null=True,
        blank=True,
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        related_name='security_events',
        null=True,
        blank=True,
    )
    auth_session_id = models.UUIDField(null=True, blank=True, db_index=True)
    request_id = models.CharField(max_length=100, blank=True, db_index=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    result = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='acknowledged_security_events',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['restaurant', '-created_at'], name='security_rest_created_idx'),
            models.Index(fields=['severity', '-created_at'], name='security_sev_created_idx'),
        ]
