from django.db import models

from common.models import BaseModel


class Hall(BaseModel):
    zone_or_cabin = models.ForeignKey(
        'floor.ZoneOrCabin',
        on_delete=models.PROTECT,
        related_name='halls',
    )
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    grid_columns = models.PositiveIntegerField(default=8)
    service_fee_enabled = models.BooleanField(default=False)
    service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    @property
    def restaurant(self):
        return self.zone_or_cabin.restaurant

    @property
    def restaurant_id(self):
        return self.zone_or_cabin.restaurant_id

    def __str__(self):
        return self.name
