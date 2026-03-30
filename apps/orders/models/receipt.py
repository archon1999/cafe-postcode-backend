from django.db import models

from common.models import BaseModel


class Receipt(BaseModel):
    class Kind(models.TextChoices):
        PREBILL = 'prebill', 'Prebill'
        FISCAL = 'fiscal', 'Fiscal'
        REFUND = 'refund', 'Refund'

    class Status(models.TextChoices):
        CREATED = 'created', 'Created'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='receipts')
    payment = models.ForeignKey('orders.Payment', on_delete=models.SET_NULL, related_name='receipts', null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FISCAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    provider = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    reprint_count = models.PositiveIntegerField(default=0)
    last_reprinted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
