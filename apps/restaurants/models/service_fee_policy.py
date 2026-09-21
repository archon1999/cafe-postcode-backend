import hashlib

from django.db import models

from common.models import BaseModel
from common.service_fee_formulas.catalog import normalize_definition


class ServiceFeePolicy(BaseModel):
    """Restaurant-owned reusable formula; sessions retain definition snapshots."""

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='service_fee_policies')
    name = models.CharField(max_length=120)
    definition = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name', 'id')

    @property
    def revision(self):
        content = f"{self.definition.get('revision', '')}:{self.is_active}"
        return hashlib.sha256(content.encode()).hexdigest()

    def save(self, *args, **kwargs):
        self.definition = normalize_definition({**self.definition, 'name': self.name})
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'definition'}
        return super().save(*args, **kwargs)
