from django.db import models

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

