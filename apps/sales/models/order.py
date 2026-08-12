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

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='orders')
    table_session = models.ForeignKey(
        'floor.TableSession',
        on_delete=models.SET_NULL,
        related_name='orders',
        null=True,
        blank=True,
    )
    distribution_point = models.ForeignKey(
        'restaurants.DistributionPoint',
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
    display_name = models.CharField(max_length=120, blank=True, default='')
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.HALL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    guest_count = models.PositiveIntegerField(default=1)
    note = models.TextField(blank=True)
    delivery_phone = models.CharField(max_length=20, blank=True, default='')
    delivery_address = models.TextField(blank=True, default='')
    subtotal = models.PositiveIntegerField(default=0)
    calculated_total = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    total_override = models.PositiveIntegerField(null=True, blank=True)
    total_override_reason = models.CharField(max_length=255, blank=True, default='')
    total_overridden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='total_overridden_orders',
        null=True,
        blank=True,
    )
    total_overridden_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            scoped_status_index('restaurant', name='order_restaurant_status_idx'),
            scoped_timestamp_index('restaurant', 'closed_at', name='order_restaurant_closed_idx'),
            scoped_timestamp_index('restaurant', 'created_at', name='order_restaurant_created_idx'),
            models.Index(fields=['restaurant', 'status', '-created_at'], name='order_open_checks_idx'),
            models.Index(fields=['restaurant', 'status', '-closed_at'], name='order_closed_checks_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'order_number'), name='orders_unique_restaurant_order_number'),
        ]

    def __init__(self, *args, **kwargs):
        branch = kwargs.pop('branch', None)
        if branch is not None and 'restaurant' not in kwargs:
            kwargs['restaurant'] = branch
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f'Order #{self.order_number}'

    @property
    def branch(self):
        return self.restaurant

    @branch.setter
    def branch(self, value):
        self.restaurant = value

    def recalculate_totals(self, *, preserve_override=False):
        from .order_item import OrderItem

        active_items = self.items.exclude(status=OrderItem.Status.CANCELLED)
        subtotal = active_items.aggregate(total=models.Sum('line_total')).get('total') or 0
        service_fee = 0

        if getattr(self.restaurant, 'service_fee_enabled', False):
            percent = getattr(self.restaurant, 'service_fee_percent', self.DEFAULT_HALL_SERVICE_FEE_PERCENT) or 0
            service_fee = round(subtotal * percent / 100)

        calculated_total = subtotal + service_fee
        self.subtotal = subtotal
        self.calculated_total = calculated_total
        if preserve_override and self.total_override is not None:
            self.total = self.total_override
            update_fields = ['subtotal', 'calculated_total', 'total', 'updated_at']
        else:
            self.total = calculated_total
            self.total_override = None
            self.total_override_reason = ''
            self.total_overridden_by = None
            self.total_overridden_at = None
            update_fields = [
                'subtotal',
                'calculated_total',
                'total',
                'total_override',
                'total_override_reason',
                'total_overridden_by',
                'total_overridden_at',
                'updated_at',
            ]
        self.save(update_fields=update_fields)
