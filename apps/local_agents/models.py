import hashlib
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from common.models import BaseModel


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def generate_agent_token() -> str:
    return f'cpa_{secrets.token_urlsafe(32)}'


class LocalAgent(BaseModel):
    class Status(models.TextChoices):
        OFFLINE = 'offline', 'Offline'
        ONLINE = 'online', 'Online'

    restaurant = models.OneToOneField('restaurants.Restaurant', on_delete=models.CASCADE, related_name='local_agent')
    device = models.OneToOneField(
        'devices.Device',
        on_delete=models.SET_NULL,
        related_name='local_agent_record',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    version = models.CharField(max_length=50, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    lan_endpoints = models.JSONField(default=list, blank=True)
    protocol_version = models.PositiveSmallIntegerField(default=1)
    rollout_state = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    credential_migrated_at = models.DateTimeField(blank=True, null=True)

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
    def authenticate_token(cls, token: str, *, allow_migrated: bool = False) -> 'LocalAgent | None':
        digest = hash_agent_token(token)
        queryset = cls.objects.select_related('restaurant').filter(token_hash=digest, is_active=True)
        if not allow_migrated:
            queryset = queryset.filter(credential_migrated_at__isnull=True)
        return queryset.first()

    def is_online(self, *, max_age_seconds: int = 75) -> bool:
        if self.status != self.Status.ONLINE or self.last_seen_at is None:
            return False
        return self.last_seen_at >= timezone.now() - timedelta(seconds=max_age_seconds)


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
    financial_operation_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['agent', 'status'], name='local_agent_agent_i_3c3563_idx'),
            models.Index(fields=['created_at'], name='local_agent_created_601553_idx'),
        ]

    def __str__(self):
        return f'{self.command_type}:{self.status}:{self.id}'


class LocalAgentConnection(BaseModel):
    """The single WebSocket allowed to act for one Local Agent record.

    A workstation can temporarily retain an older Agent executable or config
    after an update.  Persisting the authority lease in PostgreSQL keeps all
    Daphne workers consistent and prevents those duplicate sockets from both
    receiving commands or overwriting the observed runtime version.
    """

    agent = models.OneToOneField(
        LocalAgent,
        on_delete=models.CASCADE,
        related_name='connection_authority',
    )
    connection_id = models.UUIDField(null=True, blank=True)
    runtime_instance_id = models.CharField(max_length=128, blank=True)
    version = models.CharField(max_length=50, blank=True)
    protocol_version = models.PositiveSmallIntegerField(default=1)
    identity_attested = models.BooleanField(default=False)
    channel_name = models.CharField(max_length=255, blank=True)
    connected = models.BooleanField(default=False)
    connected_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    def __str__(self):
        return f'{self.agent_id}:{self.version or "legacy"}:{"online" if self.connected else "offline"}'


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


class LocalAgentMutationInbox(BaseModel):
    """Durable received evidence; APPLIED is committed with the DB projection."""
    class State(models.TextChoices):
        RECEIVED = 'received', 'Received'
        APPLIED = 'applied', 'Applied'
        NEEDS_REVIEW = 'needs_review', 'Needs review'
        CONFLICT = 'conflict', 'Conflict'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.PROTECT)
    operation_id = models.CharField(max_length=128, unique=True)
    payload_hash = models.CharField(max_length=64)
    operation = models.JSONField()
    event_version = models.PositiveSmallIntegerField(default=1)
    owner_epoch = models.CharField(max_length=128, blank=True)
    sequence = models.PositiveBigIntegerField(null=True, blank=True)
    depends_on = models.JSONField(default=list)
    occurred_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.RECEIVED)
    applied_at = models.DateTimeField(null=True, blank=True)
    last_result = models.JSONField(default=dict)

    class Meta:
        indexes = [models.Index(fields=['restaurant', 'state'], name='agent_inbox_rest_state_idx')]
        constraints = [models.UniqueConstraint(
            fields=['restaurant', 'owner_epoch', 'sequence'],
            condition=models.Q(sequence__isnull=False) & ~models.Q(owner_epoch=''),
            name='agent_inbox_owner_sequence_uniq',
        )]


class LocalAgentMutationAttempt(BaseModel):
    inbox = models.ForeignKey(LocalAgentMutationInbox, on_delete=models.PROTECT, related_name='attempts')
    payload_hash = models.CharField(max_length=64)
    operation = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
