from django.db import models

from common.models import BaseModel


class DistributionPoint(BaseModel):
    class Kind(models.TextChoices):
        HALL = 'hall', 'Hall'
        ONLINE = 'online', 'Online'
        TAKEAWAY = 'takeaway', 'Takeaway'
        DELIVERY = 'delivery', 'Delivery'

    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='distribution_points')
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.HALL)
    integration_channel = models.CharField(max_length=120, blank=True)
    assigned_hall = models.ForeignKey(
        'floor.Hall',
        on_delete=models.SET_NULL,
        related_name='distribution_points',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
