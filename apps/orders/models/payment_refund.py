from django.conf import settings
from django.db import models

from common.indexes import state_timestamp_index
from common.models import BaseModel


class PaymentRefund(BaseModel):
    class Status(models.TextChoices):
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    payment = models.ForeignKey('orders.Payment', on_delete=models.CASCADE, related_name='refunds')
    amount = models.PositiveIntegerField(default=0)
    reason = models.TextField(blank=True)
    refunded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='payment_refunds',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCEEDED)
    external_ref = models.CharField(max_length=120, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            state_timestamp_index('status', 'refunded_at', name='paymentrefund_status_idx'),
        ]
