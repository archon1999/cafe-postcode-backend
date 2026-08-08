from django.db import models
from django.db.models import Q

from common.models import BaseModel


class KitchenAnnouncement(BaseModel):
    class Kind(models.TextChoices):
        AUTO = 'auto', 'Automatic'
        REPLAY = 'replay', 'Replay'

    class Locale(models.TextChoices):
        UZ = 'uz', 'Uzbek'
        RU = 'ru', 'Russian'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='kitchen_announcements',
    )
    order = models.ForeignKey(
        'sales.Order',
        on_delete=models.CASCADE,
        related_name='kitchen_announcements',
    )
    display_name = models.CharField(max_length=64)
    locale = models.CharField(max_length=8, choices=Locale.choices, default=Locale.UZ)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.AUTO)
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        related_name='created_kitchen_announcements',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('order',),
                condition=Q(kind='auto'),
                name='unique_auto_kitchen_announcement',
            ),
        ]
        indexes = [
            models.Index(fields=('restaurant', 'created_at'), name='ka_rest_created_idx'),
        ]
