import hashlib

from django.conf import settings
from django.db import models

from common.models import BaseModel


class AdminRefreshFamily(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        REVOKED = 'revoked', 'Revoked'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_refresh_families')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    absolute_expires_at = models.DateTimeField(db_index=True)
    last_activity_at = models.DateTimeField(db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    reuse_detected_at = models.DateTimeField(null=True, blank=True)
    mfa_verified_at = models.DateTimeField(null=True, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['user', 'status', 'absolute_expires_at'], name='admin_rf_user_status_exp')]


class AdminRefreshToken(BaseModel):
    family = models.ForeignKey(AdminRefreshFamily, on_delete=models.CASCADE, related_name='tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        related_name='replaces',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['family', 'used_at', 'revoked_at'], name='admin_rt_family_state')]

    @staticmethod
    def build_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()


class AdminMFAProfile(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_mfa_profile')
    encrypted_secret = models.TextField()
    confirmed_at = models.DateTimeField()
    last_totp_counter = models.BigIntegerField(null=True, blank=True)
    last_totp_code_digest = models.CharField(max_length=64, blank=True)
    recovery_code_hashes = models.JSONField(default=list, blank=True)
    recovery_codes_generated_at = models.DateTimeField(null=True, blank=True)


class AdminMFAChallenge(BaseModel):
    class Kind(models.TextChoices):
        LOGIN = 'login', 'Login'
        ENROLLMENT = 'enrollment', 'Enrollment'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_mfa_challenges')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    pending_secret_encrypted = models.TextField(blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['user', 'kind', 'expires_at'], name='admin_mfa_user_kind_exp')]

    @staticmethod
    def build_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()
