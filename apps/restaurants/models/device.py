from django.db import models

from common.models import BaseModel


class Device(BaseModel):
    class Mode(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        WAITER = 'waiter', 'Waiter'
        CASHIER = 'cashier', 'Cashier'
        KITCHEN = 'kitchen_display', 'Kitchen Display'
        OWNER = 'owner_dashboard', 'Owner Dashboard'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='devices')
    name = models.CharField(max_length=255)
    mode = models.CharField(max_length=30, choices=Mode.choices)
    primary_hall = models.ForeignKey(
        'floor.Hall',
        on_delete=models.SET_NULL,
        related_name='primary_devices',
        null=True,
        blank=True,
    )
    allowed_halls = models.ManyToManyField('floor.Hall', blank=True, related_name='allowed_devices')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
