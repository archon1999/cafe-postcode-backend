from django.db import models

from common.models import BaseModel


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
