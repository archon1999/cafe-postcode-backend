from django.db import models

from common.models import BaseModel


class Permission(BaseModel):
    class Surface(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        POS = 'pos', 'POS'
        DASHBOARD = 'dashboard', 'Dashboard'
        SYSTEM = 'system', 'System'

    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    surface = models.CharField(max_length=20, choices=Surface.choices, default=Surface.SYSTEM)
    resource = models.CharField(max_length=120, default='')
    action = models.CharField(max_length=60, default='')
    ui_visible = models.BooleanField(default=True)
    group_key = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        ordering = ('code',)

    def __str__(self):
        return self.code
