from django.db import models

from common.models import BaseModel


class OrderItemNote(BaseModel):
    order_item = models.ForeignKey('sales.OrderItem', on_delete=models.CASCADE, related_name='notes')
    body = models.TextField()

    class Meta:
        ordering = ('created_at',)
