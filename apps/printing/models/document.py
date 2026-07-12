from django.conf import settings
from django.db import models

from common.models import BaseModel

from .template import PrintTemplate, PrintTemplateVersion


class PrintDocument(BaseModel):
    class OperationType(models.TextChoices):
        SALE = 'sale', 'Sale'
        REFUND = 'refund', 'Refund'
        TEST = 'test', 'Test'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='print_documents',
    )
    kind = models.CharField(max_length=40, choices=PrintTemplate.Kind.choices)
    operation_type = models.CharField(
        max_length=20,
        choices=OperationType.choices,
        default=OperationType.SALE,
    )
    idempotency_key = models.CharField(max_length=80)
    source_model = models.CharField(max_length=80, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    data_snapshot = models.JSONField(default=dict)
    template_version = models.ForeignKey(
        PrintTemplateVersion,
        on_delete=models.PROTECT,
        related_name='documents',
    )
    content_hash = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_print_documents',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'idempotency_key'),
                name='prt_doc_idem_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=('restaurant', 'kind', 'created_at'), name='prt_doc_rest_kind_created'),
            models.Index(fields=('source_model', 'source_id'), name='prt_doc_source_idx'),
        ]


class PrintJob(BaseModel):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RENDERING = 'rendering', 'Rendering'
        DISPATCHED = 'dispatched', 'Dispatched'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        DISPATCH_UNKNOWN = 'dispatch_unknown', 'Dispatch unknown'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='print_jobs',
    )
    document = models.ForeignKey(PrintDocument, on_delete=models.PROTECT, related_name='jobs')
    idempotency_key = models.CharField(max_length=80)
    cash_desk = models.ForeignKey(
        'restaurants.CashDesk',
        on_delete=models.SET_NULL,
        related_name='print_jobs',
        null=True,
        blank=True,
    )
    prep_station = models.ForeignKey(
        'restaurants.PrepStation',
        on_delete=models.SET_NULL,
        related_name='print_jobs',
        null=True,
        blank=True,
    )
    printer_integration = models.ForeignKey(
        'integrations.IntegrationConfig',
        on_delete=models.SET_NULL,
        related_name='print_jobs',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    copies = models.PositiveSmallIntegerField(default=1)
    attempts = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'idempotency_key'),
                name='prt_job_idem_uniq',
            ),
            models.CheckConstraint(check=models.Q(copies__gte=1), name='prt_job_copies_gte_1'),
        ]
        indexes = [
            models.Index(fields=('restaurant', 'status', 'created_at'), name='prt_job_rest_status_created'),
        ]
