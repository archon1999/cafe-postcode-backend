import hashlib

from django.conf import settings
from django.db import models

from common.models import BaseModel


class AuthSession(BaseModel):
    class Surface(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        POS = 'pos', 'POS'
        DASHBOARD = 'dashboard', 'Dashboard'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        REVOKED = 'revoked', 'Revoked'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auth_sessions')
    device = models.ForeignKey(
        'devices.Device',
        on_delete=models.CASCADE,
        related_name='auth_sessions',
        null=True,
        blank=True,
    )
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='auth_sessions',
        null=True,
        blank=True,
    )
    token_key_hash = models.CharField(max_length=64, unique=True)
    surface = models.CharField(max_length=20, choices=Surface.choices)
    expires_at = models.DateTimeField()
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    refresh_family = models.ForeignKey(
        'users.AdminRefreshFamily',
        on_delete=models.CASCADE,
        related_name='access_sessions',
        null=True,
        blank=True,
    )
    mfa_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    @staticmethod
    def build_token_key_hash(token_key: str) -> str:
        return hashlib.sha256(token_key.encode('utf-8')).hexdigest()
