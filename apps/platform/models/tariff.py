from django.db import models

from common.models import BaseModel


class Tariff(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    permissions = models.ManyToManyField('users.Permission', blank=True, related_name='tariffs')
    allowed_roles = models.ManyToManyField('users.Role', blank=True, related_name='tariffs')

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
