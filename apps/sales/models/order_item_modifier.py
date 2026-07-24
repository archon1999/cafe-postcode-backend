from django.db import models

from common.models import BaseModel


class OrderItemModifier(BaseModel):
    order_item = models.ForeignKey(
        'sales.OrderItem',
        on_delete=models.CASCADE,
        related_name='modifiers',
    )
    modifier_option = models.ForeignKey(
        'catalog.ModifierOption',
        on_delete=models.SET_NULL,
        related_name='order_item_snapshots',
        null=True,
        blank=True,
    )
    group_name = models.CharField(max_length=255)
    option_name = models.CharField(max_length=255)
    price_delta = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'created_at')

    def __str__(self):
        return f'{self.order_item_id}: {self.group_name} / {self.option_name}'
