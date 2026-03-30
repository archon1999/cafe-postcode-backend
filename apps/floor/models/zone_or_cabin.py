from django.db import models

from common.models import BaseModel

from .hall import Hall


class ZoneOrCabin(BaseModel):
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name='zones')
    name = models.CharField(max_length=255)
    is_private = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return f'{self.hall.name} - {self.name}'
