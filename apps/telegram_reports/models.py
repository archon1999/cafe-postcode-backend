import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from common.models import BaseModel


class TelegramAccount(BaseModel):
    class State(models.TextChoices):
        IDLE = "idle", "Idle"
        AWAITING_CONNECT = "awaiting_connect", "Awaiting branch codes"

    telegram_user_id = models.BigIntegerField(unique=True)
    chat_id = models.BigIntegerField()
    username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    language_code = models.CharField(max_length=16, blank=True)
    notifications_enabled = models.BooleanField(default=True)
    state = models.CharField(max_length=32, choices=State.choices, default=State.IDLE)
    last_interaction_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("telegram_user_id",)

    def __str__(self):
        return self.username or self.first_name or str(self.telegram_user_id)


class TelegramBranchSubscription(BaseModel):
    account = models.ForeignKey(
        TelegramAccount,
        on_delete=models.CASCADE,
        related_name="branch_subscriptions",
    )
    restaurant = models.ForeignKey(
        "restaurants.Restaurant",
        on_delete=models.CASCADE,
        related_name="telegram_subscriptions",
    )

    class Meta:
        ordering = ("restaurant__name",)
        constraints = [
            models.UniqueConstraint(
                fields=("account", "restaurant"),
                name="telegram_unique_account_branch",
            )
        ]

    def __str__(self):
        return f"{self.account_id}:{self.restaurant.name}"


class TelegramLinkToken(BaseModel):
    restaurant = models.ForeignKey(
        "restaurants.Restaurant",
        on_delete=models.CASCADE,
        related_name="telegram_link_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.ForeignKey(
        TelegramAccount,
        on_delete=models.SET_NULL,
        related_name="consumed_link_tokens",
        null=True,
        blank=True,
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="issued_telegram_link_tokens",
        null=True,
        blank=True,
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("restaurant", "expires_at"),
                name="telegram_link_rest_exp_idx",
            ),
        ]

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    @transaction.atomic
    def issue(cls, *, restaurant, issued_by, ttl_minutes: int = 5):
        now = timezone.now()
        restaurant.__class__.objects.select_for_update().get(pk=restaurant.pk)
        cls.objects.filter(
            restaurant=restaurant,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).update(revoked_at=now, updated_at=now)
        raw_token = f"tgr_{secrets.token_urlsafe(32)}"
        token = cls.objects.create(
            restaurant=restaurant,
            token_hash=cls.hash_token(raw_token),
            expires_at=now + timedelta(minutes=max(1, min(ttl_minutes, 10))),
            issued_by=issued_by,
        )
        return token, raw_token

    @classmethod
    @transaction.atomic
    def consume(cls, *, raw_token: str, account: TelegramAccount):
        now = timezone.now()
        token = (
            cls.objects.select_for_update()
            .select_related("restaurant")
            .filter(
                token_hash=cls.hash_token(raw_token),
                consumed_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=now,
            )
            .first()
        )
        if token is None or not token.restaurant.is_active:
            return None, False

        _, created = TelegramBranchSubscription.objects.get_or_create(
            account=account,
            restaurant=token.restaurant,
        )
        token.consumed_at = now
        token.consumed_by = account
        token.save(update_fields=("consumed_at", "consumed_by", "updated_at"))
        return token, created


class TelegramProcessedUpdate(BaseModel):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    update_id = models.BigIntegerField(unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)


class TelegramReportDelivery(BaseModel):
    class ReportType(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        TelegramAccount,
        on_delete=models.CASCADE,
        related_name="report_deliveries",
    )
    restaurant = models.ForeignKey(
        "restaurants.Restaurant",
        on_delete=models.CASCADE,
        related_name="telegram_report_deliveries",
    )
    report_type = models.CharField(max_length=20, choices=ReportType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-period_end", "restaurant__name")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "restaurant", "report_type", "period_start", "period_end"),
                name="telegram_unique_report_delivery",
            )
        ]
        indexes = [
            models.Index(fields=("status", "created_at"), name="telegram_delivery_status_idx"),
        ]
