from django.db import models

from apps.integrations.fields import EncryptedJSONField
from common.models import BaseModel


class IntegrationConfig(BaseModel):
    class Kind(models.TextChoices):
        FISCAL = 'fiscal', 'Fiscal'
        PAYMENT = 'payment', 'Payment'
        PRINTER = 'printer', 'Printer'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='integration_configs',
    )
    name = models.CharField(max_length=120, blank=True, default='')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    provider = models.CharField(max_length=120)
    is_enabled = models.BooleanField(default=True)
    # The original plaintext ``settings`` database column is intentionally
    # retained during the rollback window. Runtime reads/writes use only this
    # encrypted shadow column; migration 0013 can repopulate the legacy column
    # before an application rollback.
    settings = EncryptedJSONField(default=dict, blank=True, db_column='settings_encrypted')

    class Meta:
        ordering = ('kind', 'provider')

    def __str__(self):
        return self.name or f'{self.kind}:{self.provider}'
