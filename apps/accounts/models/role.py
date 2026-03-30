from django.db import models

from common.models import BaseModel

from .permission import Permission


class Role(BaseModel):
    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=True)
    permissions = models.ManyToManyField(Permission, blank=True, related_name='roles')

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
