from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models import BaseModel


class OrderItemMarking(BaseModel):
    order_item = models.ForeignKey('sales.OrderItem', on_delete=models.CASCADE, related_name='markings')
    catalog_item = models.ForeignKey('catalog.CatalogItem', on_delete=models.PROTECT, related_name='order_item_markings')
    raw_code = models.CharField(max_length=512)
    gtin = models.CharField(max_length=32, blank=True, db_index=True)
    serial = models.CharField(max_length=256, blank=True)
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='scanned_order_item_markings',
        null=True,
        blank=True,
    )
    scanned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('scanned_at', 'created_at')
        constraints = [
            models.UniqueConstraint(fields=['catalog_item', 'raw_code'], name='uniq_order_item_marking_catalog_raw'),
        ]
        indexes = [
            models.Index(fields=['order_item', 'gtin'], name='order_mark_item_gtin_idx'),
        ]

    def __str__(self):
        return self.raw_code
