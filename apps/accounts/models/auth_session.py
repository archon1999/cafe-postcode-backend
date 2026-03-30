import hashlib

from django.conf import settings
from django.db import models

from common.models import BaseModel


class AuthSession(BaseModel):
    class UiChannel(models.TextChoices):
        POS = 'pos', 'POS'
        ADMIN = 'admin', 'Admin'
        DASHBOARD = 'dashboard', 'Dashboard'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        REVOKED = 'revoked', 'Revoked'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auth_sessions')
    token_key_hash = models.CharField(max_length=64, unique=True)
    ui_channel = models.CharField(max_length=20, choices=UiChannel.choices)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    @staticmethod
    def build_token_key_hash(token_key: str) -> str:
        return hashlib.sha256(token_key.encode('utf-8')).hexdigest()

