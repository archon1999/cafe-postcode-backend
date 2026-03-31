from django.conf import settings
from django.db import models

from common.indexes import scoped_status_index
from common.models import BaseModel


class TableSession(BaseModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
        CLOSED = 'closed', 'Closed'
        MERGED = 'merged', 'Merged'

    restaurant = models.ForeignKey(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='table_sessions',
    )
    hall = models.ForeignKey('floor.Hall', on_delete=models.CASCADE, related_name='table_sessions')
    table = models.ForeignKey('floor.DiningTable', on_delete=models.CASCADE, related_name='table_sessions')
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='opened_table_sessions',
        null=True,
        blank=True,
    )
    assigned_waiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='assigned_table_sessions',
        null=True,
        blank=True,
    )
    guest_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    note = models.TextField(blank=True)
    merged_into = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        related_name='merged_children',
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            scoped_status_index('restaurant', name='tblsess_rest_status_idx'),
        ]

    def __str__(self):
        return f'{self.table.name} ({self.get_status_display()})'
