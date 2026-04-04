from django.db import models

from common.models import BaseModel


class Permission(BaseModel):
    class Surface(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        POS = 'pos', 'POS'
        DASHBOARD = 'dashboard', 'Dashboard'

    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    surface = models.CharField(max_length=20, choices=Surface.choices, default=Surface.ADMIN)
    resource = models.CharField(max_length=120, default='')
    action = models.CharField(max_length=60, default='')
    ui_visible = models.BooleanField(default=True)
    group_key = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        ordering = ('code',)

    def __str__(self):
        return self.code


class PermissionEndpoint(BaseModel):
    permission = models.ForeignKey('accounts.Permission', on_delete=models.CASCADE, related_name='endpoints')
    url = models.CharField(max_length=255)
    method = models.CharField(max_length=16)

    class Meta:
        ordering = ('url', 'method')
        constraints = [
            models.UniqueConstraint(
                fields=('permission', 'url', 'method'),
                name='accounts_permission_endpoint_permission_route_method_uniq',
            ),
        ]

    def save(self, *args, **kwargs):
        self.method = self.method.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.method} {self.url}'
