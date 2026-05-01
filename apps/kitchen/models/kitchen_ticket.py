from django.db import models

from common.models import BaseModel


class KitchenTicket(BaseModel):
    class Status(models.TextChoices):
        NEW = 'new', 'New'
        COOKING = 'cooking', 'Cooking'
        DONE = 'done', 'Done'

    class RouteMode(models.TextChoices):
        DISPLAY = 'display', 'Display'
        PRINTER = 'printer', 'Printer'
        BOTH = 'both', 'Both'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='kitchen_tickets',
    )
    order = models.ForeignKey('sales.Order', on_delete=models.CASCADE, related_name='kitchen_tickets')
    prep_station = models.ForeignKey(
        'restaurants.PrepStation',
        on_delete=models.CASCADE,
        related_name='kitchen_tickets',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    routed_via = models.CharField(max_length=20, choices=RouteMode.choices, default=RouteMode.DISPLAY)
    is_printed = models.BooleanField(default=False)
    printed_payload = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        unique_together = ('order', 'prep_station')
        indexes = [
            models.Index(fields=['restaurant', 'status', 'created_at'], name='kt_rest_status_created_idx'),
            models.Index(fields=['restaurant', 'status', 'completed_at'], name='kt_rest_status_done_idx'),
        ]
