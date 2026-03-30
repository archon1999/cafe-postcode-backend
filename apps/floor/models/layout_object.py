from django.db import models

from common.models import BaseModel

from .dining_table import DiningTable
from .hall import Hall
from .zone_or_cabin import ZoneOrCabin


class LayoutObject(BaseModel):
    class Kind(models.TextChoices):
        TABLE = 'table', 'Table'
        BAR = 'bar', 'Bar'
        CASH_DESK = 'cash_desk', 'Cash Desk'
        DOOR = 'door', 'Door'
        WALL = 'wall', 'Wall'
        DECOR = 'decor', 'Decor'
        LABEL = 'label', 'Label'

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='layout_objects')
    zone = models.ForeignKey(
        ZoneOrCabin,
        on_delete=models.SET_NULL,
        related_name='layout_objects',
        null=True,
        blank=True,
    )
    table = models.ForeignKey(
        DiningTable,
        on_delete=models.SET_NULL,
        related_name='layout_objects',
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    label = models.CharField(max_length=255, blank=True)
    position_x = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    position_y = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    width = models.DecimalField(max_digits=8, decimal_places=2, default=120)
    height = models.DecimalField(max_digits=8, decimal_places=2, default=120)
    rotation = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    payload = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'created_at')
