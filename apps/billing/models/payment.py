from django.conf import settings
from django.db import models

from common.indexes import state_timestamp_index
from common.models import BaseModel


class Payment(BaseModel):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        QR = 'qr', 'QR'
        MIXED = 'mixed', 'Mixed'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    order = models.ForeignKey('sales.Order', on_delete=models.CASCADE, related_name='payments')
    cash_desk = models.ForeignKey(
        'restaurants.CashDesk',
        on_delete=models.SET_NULL,
        related_name='payments',
        null=True,
        blank=True,
    )
    cash_shift = models.ForeignKey(
        'billing.CashShift',
        on_delete=models.SET_NULL,
        related_name='payments',
        null=True,
        blank=True,
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='payments_received',
        null=True,
        blank=True,
    )
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    amount = models.PositiveIntegerField(default=0)
    cash_amount = models.PositiveIntegerField(default=0)
    card_amount = models.PositiveIntegerField(default=0)
    fiscal_cash_amount = models.PositiveIntegerField(default=0)
    fiscal_card_amount = models.PositiveIntegerField(default=0)
    fiscal_adjustment_reason = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    register_fiscal = models.BooleanField(default=True)
    external_ref = models.CharField(max_length=120, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    edge_operation_id = models.CharField(max_length=128, unique=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        amount = int(self.amount or 0)
        if amount and not self.cash_amount and not self.card_amount:
            if self.method == self.Method.CASH:
                self.cash_amount = amount
            elif self.method in {self.Method.CARD, self.Method.QR}:
                self.card_amount = amount
        if amount and not self.fiscal_cash_amount and not self.fiscal_card_amount:
            self.fiscal_cash_amount = int(self.cash_amount or 0)
            self.fiscal_card_amount = int(self.card_amount or 0)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            state_timestamp_index('status', 'paid_at', name='payment_status_paid_idx'),
            models.Index(fields=['order', 'status'], name='payment_order_status_idx'),
            models.Index(fields=['cash_shift', 'status'], name='payment_shift_status_idx'),
        ]
