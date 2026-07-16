import hashlib

from django.db import models

from common.models import BaseModel


def hash_tv_monitor_secret(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TvMonitorDevice(BaseModel):
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='tv_monitor_devices',
    )
    token_hash = models.CharField(max_length=64, unique=True)
    restaurant_auth_code_hash = models.CharField(max_length=64)
    paired_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['restaurant', 'revoked_at'], name='tv_device_rest_revoked_idx'),
        ]


class TvMonitorPairing(BaseModel):
    poll_token_hash = models.CharField(max_length=64, unique=True)
    claim_token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    device = models.OneToOneField(
        TvMonitorDevice,
        on_delete=models.SET_NULL,
        related_name='pairing',
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=['claimed_at', 'expires_at'], name='tv_pair_claimed_exp_idx'),
        ]
