import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from common.models import BaseModel


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def generate_agent_token() -> str:
    return f'cpa_{secrets.token_urlsafe(32)}'


def generate_enrollment_token() -> str:
    return f'cpe_{secrets.token_urlsafe(32)}'


class LocalAgent(BaseModel):
    class Status(models.TextChoices):
        OFFLINE = 'offline', 'Offline'
        ONLINE = 'online', 'Online'

    restaurant = models.OneToOneField('restaurants.Restaurant', on_delete=models.CASCADE, related_name='local_agent')
    name = models.CharField(max_length=255, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    version = models.CharField(max_length=50, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    lan_endpoints = models.JSONField(default=list, blank=True)
    protocol_version = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('restaurant__name',)

    def __str__(self):
        return f'{self.restaurant_id}:{self.name or "local-agent"}'

    @classmethod
    def issue_for_restaurant(cls, *, restaurant, name: str = '', version: str = '') -> tuple['LocalAgent', str]:
        token = generate_agent_token()
        agent, _ = cls.objects.update_or_create(
            restaurant=restaurant,
            defaults={
                'name': name or 'Local Agent',
                'token_hash': hash_agent_token(token),
                'status': cls.Status.OFFLINE,
                'last_seen_at': None,
                'version': version or '',
                'capabilities': ['local_http', 'printer', 'marta_discovery'],
                'lan_endpoints': [],
                'protocol_version': 1,
                'is_active': True,
            },
        )
        return agent, token

    @classmethod
    def authenticate_token(cls, token: str) -> 'LocalAgent | None':
        digest = hash_agent_token(token)
        return cls.objects.select_related('restaurant').filter(token_hash=digest, is_active=True).first()

    def is_online(self, *, max_age_seconds: int = 75) -> bool:
        if self.status != self.Status.ONLINE or self.last_seen_at is None:
            return False
        return self.last_seen_at >= timezone.now() - timedelta(seconds=max_age_seconds)


class LocalAgentEnrollmentToken(BaseModel):
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='local_agent_enrollment_tokens',
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='issued_local_agent_enrollment_tokens',
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['restaurant', 'expires_at'], name='agent_enroll_rest_exp_idx')]

    @classmethod
    def inspect(cls, raw_token: str):
        now = timezone.now()
        token = (
            cls.objects.select_related('restaurant')
            .filter(token_hash=hash_agent_token(raw_token), used_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if token is None or not token.restaurant.is_active:
            return None
        return token

    @classmethod
    @transaction.atomic
    def issue(cls, *, restaurant, issued_by=None, ttl_minutes: int = 15):
        restaurant.__class__.objects.select_for_update().get(pk=restaurant.pk)
        raw_token = generate_enrollment_token()
        now = timezone.now()
        cls.objects.filter(restaurant=restaurant, used_at__isnull=True, expires_at__gt=now).update(used_at=now)
        token = cls.objects.create(
            restaurant=restaurant,
            token_hash=hash_agent_token(raw_token),
            expires_at=now + timedelta(minutes=max(1, min(ttl_minutes, 60))),
            issued_by=issued_by,
        )
        return token, raw_token

    @classmethod
    @transaction.atomic
    def consume(cls, raw_token: str):
        now = timezone.now()
        token = (
            cls.objects.select_for_update()
            .select_related('restaurant')
            .filter(token_hash=hash_agent_token(raw_token), used_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if token is None or not token.restaurant.is_active:
            return None
        token.used_at = now
        token.save(update_fields=['used_at', 'updated_at'])
        return token


class LocalAgentCommand(BaseModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        TIMED_OUT = 'timed_out', 'Timed out'

    agent = models.ForeignKey(LocalAgent, on_delete=models.CASCADE, related_name='commands')
    command_type = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.JSONField(default=dict, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=30)
    sent_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['agent', 'status'], name='local_agent_agent_i_3c3563_idx'),
            models.Index(fields=['created_at'], name='local_agent_created_601553_idx'),
        ]

    def __str__(self):
        return f'{self.command_type}:{self.status}:{self.id}'


class LocalAgentMutationReceipt(BaseModel):
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='local_agent_mutation_receipts',
    )
    operation_id = models.CharField(max_length=128, unique=True)
    user_id = models.UUIDField()
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('created_at',)
        indexes = [models.Index(fields=['restaurant', 'created_at'], name='agent_mut_rest_created_idx')]
