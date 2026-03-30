from django.db import models

from common.models import BaseModel


class Permission(BaseModel):
    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ('code',)

    def __str__(self):
        return self.code
