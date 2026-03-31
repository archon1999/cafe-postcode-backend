from django.conf import settings
from django.db import models

from common.indexes import scoped_status_index, scoped_timestamp_index
from common.models import BaseModel


class Order(BaseModel):
    DEFAULT_HALL_SERVICE_FEE_PERCENT = 10

    class Channel(models.TextChoices):
        HALL = 'hall', 'Hall'
        TAKEAWAY = 'takeaway', 'Takeaway'
        ONLINE = 'online', 'Online'
        DELIVERY = 'delivery', 'Delivery'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        SUBMITTED = 'submitted', 'Submitted'
        READY = 'ready', 'Ready'
        CLOSED = 'closed', 'Closed'
        CANCELLED = 'cancelled', 'Cancelled'

    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='orders')
    table_session = models.ForeignKey(
        'floor.TableSession',
        on_delete=models.SET_NULL,
        related_name='orders',
        null=True,
        blank=True,
    )
    distribution_point = models.ForeignKey(
        'organizations.DistributionPoint',
        on_delete=models.SET_NULL,
        related_name='orders',
        null=True,
        blank=True,
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='opened_orders',
        null=True,
        blank=True,
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='closed_orders',
        null=True,
        blank=True,
    )
    order_number = models.PositiveIntegerField(default=1)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.HALL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    guest_count = models.PositiveIntegerField(default=1)
    note = models.TextField(blank=True)
    subtotal = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            scoped_status_index('restaurant', name='order_restaurant_status_idx'),
            scoped_timestamp_index('restaurant', 'closed_at', name='order_restaurant_closed_idx'),
            scoped_timestamp_index('restaurant', 'created_at', name='order_restaurant_created_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'order_number'), name='orders_unique_restaurant_order_number'),
        ]

    def __str__(self):
        return f'Order #{self.order_number}'

    def recalculate_totals(self):
        from .order_item import OrderItem

        active_items = self.items.exclude(status=OrderItem.Status.CANCELLED)
        subtotal = active_items.aggregate(total=models.Sum('line_total')).get('total') or 0
        service_fee = 0

        if self.channel == self.Channel.HALL:
            percent = getattr(self.restaurant, 'service_fee_percent', self.DEFAULT_HALL_SERVICE_FEE_PERCENT) or 0
            service_fee = round(subtotal * percent / 100)

        self.subtotal = subtotal
        self.total = subtotal + service_fee
        self.save(update_fields=['subtotal', 'total', 'updated_at'])
