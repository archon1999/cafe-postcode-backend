from django.conf import settings
from django.db import models

from common.models import BaseModel


class OrderItem(BaseModel):
    class Status(models.TextChoices):
        NEW = 'new', 'New'
        COOKING = 'cooking', 'Cooking'
        DONE = 'done', 'Done'
        SERVED = 'served', 'Served'
        CANCELLED = 'cancelled', 'Cancelled'

    order = models.ForeignKey('sales.Order', on_delete=models.CASCADE, related_name='items')
    catalog_item = models.ForeignKey('catalog.CatalogItem', on_delete=models.PROTECT, related_name='order_items')
    prep_station = models.ForeignKey(
        'restaurants.PrepStation',
        on_delete=models.SET_NULL,
        related_name='order_items',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_order_items',
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.PositiveIntegerField(default=0)
    line_total = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ('created_at',)
        indexes = [
            models.Index(fields=['order', 'status'], name='orderitem_order_status_idx'),
            models.Index(fields=['prep_station', 'status'], name='orderitem_station_status_idx'),
        ]

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or 0) * (self.unit_price or 0)
        super().save(*args, **kwargs)
