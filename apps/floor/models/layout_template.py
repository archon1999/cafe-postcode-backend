from django.db import models

from common.models import BaseModel


class LayoutTemplate(BaseModel):
    restaurant = models.ForeignKey(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='layout_templates',
    )
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
