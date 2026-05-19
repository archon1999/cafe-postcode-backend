from django.conf import settings
from django.db import models

from common.indexes import scoped_status_index, scoped_timestamp_index
from common.models import BaseModel


class FiscalShiftSession(BaseModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='fiscal_shift_sessions')
    cash_desk = models.ForeignKey(
        'restaurants.CashDesk',
        on_delete=models.SET_NULL,
        related_name='fiscal_shift_sessions',
        null=True,
        blank=True,
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='opened_fiscal_shift_sessions',
        null=True,
        blank=True,
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='closed_fiscal_shift_sessions',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    provider = models.CharField(max_length=120, blank=True)
    terminal_id = models.CharField(max_length=120, blank=True)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    open_payload = models.JSONField(default=dict, blank=True)
    close_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('-opened_at',)
        indexes = [
            scoped_status_index('restaurant', name='fiscalshift_rest_status_idx'),
            scoped_timestamp_index('restaurant', 'opened_at', name='fiscalshift_rest_opened_idx'),
            models.Index(fields=['cash_desk', 'status'], name='fiscalshift_desk_status_idx'),
        ]
