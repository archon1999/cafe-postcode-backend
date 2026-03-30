from django.db import models

from common.models import BaseModel

from .restaurant import Restaurant


class Branch(BaseModel):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    legal_name = models.CharField(max_length=255, blank=True)
    tax_number = models.CharField(max_length=64, blank=True)
    vat_enabled = models.BooleanField(default=False)
    service_fee_percent = models.PositiveIntegerField(default=10)
    last_order_number = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return f'{self.restaurant.name} - {self.name}'
