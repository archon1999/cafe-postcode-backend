from django.db import models

from common.models import BaseModel


class RestaurantUserProfile(BaseModel):
    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='restaurant_profile')
    restaurant = models.ForeignKey(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='user_profiles',
    )
    pin_code = models.CharField(max_length=128, blank=True, default='')
    hall_switch_permission = models.BooleanField(default=False)
    primary_hall = models.ForeignKey(
        'floor.Hall',
        on_delete=models.SET_NULL,
        related_name='primary_restaurant_users',
        null=True,
        blank=True,
    )
    allowed_halls = models.ManyToManyField('floor.Hall', blank=True, related_name='restaurant_allowed_users')

    class Meta:
        ordering = ('user__username',)

    def __str__(self):
        return f'Restaurant user profile: {self.user.username}'
