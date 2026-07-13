from django.conf import settings
from django.db import models

from common.models import BaseModel


class PrintTemplate(BaseModel):
    class Kind(models.TextChoices):
        KITCHEN_TICKET = 'kitchen_ticket', 'Kitchen ticket'
        PAYMENT_RECEIPT_PLAIN = 'payment_receipt_plain', 'Plain payment receipt'
        PAYMENT_RECEIPT_FISCAL = 'payment_receipt_fiscal', 'Fiscal payment receipt'
        SHIFT_REPORT = 'shift_report', 'Shift report'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='print_templates',
    )
    kind = models.CharField(max_length=40, choices=Kind.choices)
    published_version = models.ForeignKey(
        'printing.PrintTemplateVersion',
        on_delete=models.SET_NULL,
        related_name='published_by_templates',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('kind',)
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'kind'),
                name='prt_tpl_rest_kind_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.restaurant_id}:{self.kind}'


class PrintTemplateVersion(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        RETIRED = 'retired', 'Retired'

    template = models.ForeignKey(PrintTemplate, on_delete=models.CASCADE, related_name='versions')
    revision = models.PositiveIntegerField()
    schema_version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    preset_key = models.CharField(max_length=40, blank=True)
    layout = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_print_template_versions',
        null=True,
        blank=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-revision',)
        constraints = [
            models.UniqueConstraint(
                fields=('template', 'revision'),
                name='prt_tpl_rev_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.template_id}:v{self.revision}:{self.status}'
