from django.db import models

from common.models import BaseModel


class Tariff(BaseModel):
    class Classification(models.TextChoices):
        BASIC = 'basic', 'Basic'
        STANDARD = 'standard', 'Standard'
        PREMIUM = 'premium', 'Premium'
        CUSTOM = 'custom', 'Custom'

    name = models.CharField(max_length=255)
    classification = models.CharField(max_length=30, choices=Classification.choices, default=Classification.BASIC)
    description = models.TextField(blank=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    yearly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    permissions = models.ManyToManyField('accounts.Permission', blank=True, related_name='tariffs')
    allowed_roles = models.ManyToManyField('accounts.Role', blank=True, related_name='tariffs')
    operational_settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
