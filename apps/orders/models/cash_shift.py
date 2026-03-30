from django.conf import settings
from django.db import models

from common.indexes import scoped_status_index, scoped_timestamp_index
from common.models import BaseModel


class CashShift(BaseModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'

    branch = models.ForeignKey('organizations.Branch', on_delete=models.CASCADE, related_name='cash_shifts')
    cash_desk = models.ForeignKey('organizations.CashDesk', on_delete=models.CASCADE, related_name='cash_shifts')
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='opened_cash_shifts',
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='closed_cash_shifts',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_cash_amount = models.PositiveIntegerField(default=0)
    actual_closing_cash_amount = models.PositiveIntegerField(default=0)
    expected_closing_cash_amount = models.PositiveIntegerField(default=0)
    cash_difference_amount = models.IntegerField(default=0)
    cash_total = models.PositiveIntegerField(default=0)
    card_total = models.PositiveIntegerField(default=0)
    qr_total = models.PositiveIntegerField(default=0)
    refund_total = models.PositiveIntegerField(default=0)
    receipt_count = models.PositiveIntegerField(default=0)
    reprint_count = models.PositiveIntegerField(default=0)
    notes_open = models.TextField(blank=True)
    notes_close = models.TextField(blank=True)

    class Meta:
        ordering = ('-opened_at',)
        indexes = [
            scoped_status_index('branch', name='cashshift_branch_status_idx'),
            scoped_timestamp_index('branch', 'opened_at', name='cashshift_branch_opened_idx'),
        ]

