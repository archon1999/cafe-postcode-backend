from django.conf import settings
from django.db import models

from common.models import BaseModel


class RestaurantBalanceTransaction(BaseModel):
    class Kind(models.TextChoices):
        TOP_UP = 'top_up', 'Top up'
        RENEWAL_CHARGE = 'renewal_charge', 'Renewal charge'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='balance_transactions',
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='restaurant_balance_transactions',
        null=True,
        blank=True,
    )
    note = models.CharField(max_length=255, blank=True, default='')
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def __str__(self):
        return f'{self.restaurant}: {self.kind} ({self.amount})'
