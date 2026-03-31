from django.db import models

from common.models import BaseModel


class Hall(BaseModel):
    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='halls')
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    grid_columns = models.PositiveIntegerField(default=8)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name
