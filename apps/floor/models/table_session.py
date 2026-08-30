from django.conf import settings
from django.db import models
from django.utils import timezone

from common.indexes import scoped_status_index
from common.models import BaseModel
from common.service_fees import build_service_fee_snapshot


class TableSession(BaseModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
        CLOSED = 'closed', 'Closed'
        MERGED = 'merged', 'Merged'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
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
    opened_at = models.DateTimeField(default=timezone.now)
    service_fee_snapshot = models.JSONField(default=list, blank=True)
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

    def capture_service_fee_snapshot(self):
        config_fields = (
            'name',
            'service_fee_enabled',
            'service_fee_mode',
            'service_fee_percent',
            'service_fee_hourly_rate',
        )
        restaurant = self._meta.get_field('restaurant').remote_field.model.objects.only(*config_fields).get(
            pk=self.restaurant_id
        )
        hall = self._meta.get_field('hall').remote_field.model.objects.only(*config_fields).get(pk=self.hall_id)
        table = self._meta.get_field('table').remote_field.model.objects.only(*config_fields).get(pk=self.table_id)
        self.service_fee_snapshot = build_service_fee_snapshot(
            restaurant=restaurant,
            hall=hall,
            table=table,
        )

    def save(self, *args, **kwargs):
        if (
            self._state.adding
            and not self.service_fee_snapshot
            and not getattr(self, '_preserve_service_fee_snapshot', False)
        ):
            self.capture_service_fee_snapshot()
        return super().save(*args, **kwargs)
