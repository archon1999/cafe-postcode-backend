from django.db import models

from common.models import BaseModel


class Receipt(BaseModel):
    class Kind(models.TextChoices):
        PLAIN = 'plain', 'Plain payment receipt'
        FISCAL = 'fiscal', 'Fiscal'
        REFUND = 'refund', 'Refund'

    class Status(models.TextChoices):
        CREATED = 'created', 'Created'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        UNKNOWN = 'unknown', 'Registration outcome unknown'

    order = models.ForeignKey('sales.Order', on_delete=models.CASCADE, related_name='receipts')
    payment = models.ForeignKey('billing.Payment', on_delete=models.SET_NULL, related_name='receipts', null=True, blank=True)
    print_document = models.ForeignKey(
        'printing.PrintDocument',
        on_delete=models.PROTECT,
        related_name='receipts',
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FISCAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    provider = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    fiscal_requested_at = models.DateTimeField(null=True, blank=True)
    fiscal_registered_at = models.DateTimeField(null=True, blank=True)
    original_paid_at = models.DateTimeField(null=True, blank=True)
    fiscal_error_code = models.CharField(max_length=32, blank=True)
    fiscal_error_message = models.TextField(blank=True)
    reprint_count = models.PositiveIntegerField(default=0)
    last_reprinted_at = models.DateTimeField(null=True, blank=True)
    split_key = models.CharField(max_length=128, blank=True)
    registration_key = models.CharField(max_length=64, null=True, blank=True, unique=True)
    fiscal_session_id = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=['payment', 'kind', 'split_key'], condition=~models.Q(split_key=''), name='receipt_payment_split_unique')]


class FiscalReceiptAttempt(BaseModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name='fiscal_attempts')
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['receipt', 'payload_hash'], name='fiscal_attempt_evidence_unique')]
