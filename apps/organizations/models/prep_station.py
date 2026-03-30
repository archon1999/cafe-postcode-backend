from django.db import models

from common.models import BaseModel


class PrepStation(BaseModel):
    class Kind(models.TextChoices):
        KITCHEN = 'kitchen', 'Kitchen'
        BAR = 'bar', 'Bar'
        OTHER = 'other', 'Other'

    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='prep_stations')
    branch = models.ForeignKey(
        'organizations.Branch',
        on_delete=models.SET_NULL,
        related_name='prep_stations',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.KITCHEN)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
