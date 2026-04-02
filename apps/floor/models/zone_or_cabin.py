from django.db import models

from common.models import BaseModel


class ZoneOrCabin(BaseModel):
    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='zones')
    name = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name
