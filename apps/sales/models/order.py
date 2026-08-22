from decimal import Decimal, ROUND_HALF_UP

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
    restaurant_service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hall_service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    table_service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
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

    @staticmethod
    def _enabled_service_fee_percent(source) -> Decimal:
        if source is None or not getattr(source, 'service_fee_enabled', False):
            return Decimal('0')
        return max(Decimal(str(getattr(source, 'service_fee_percent', 0) or 0)), Decimal('0'))

    @staticmethod
    def calculate_service_fee_amount(subtotal: int, percent) -> int:
        rate = max(Decimal(str(percent or 0)), Decimal('0'))
        if subtotal <= 0 or rate <= 0:
            return 0
        return int((Decimal(subtotal) * rate / Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def capture_service_fee_snapshot(self):
        if self.channel != self.Channel.HALL:
            self.restaurant_service_fee_percent = Decimal('0')
            self.hall_service_fee_percent = Decimal('0')
            self.table_service_fee_percent = Decimal('0')
            return

        self.restaurant_service_fee_percent = self._enabled_service_fee_percent(self.restaurant)
        hall = None
        table = None
        if self.table_session_id:
            hall = self.table_session.hall
            table = self.table_session.table
        self.hall_service_fee_percent = self._enabled_service_fee_percent(hall)
        self.table_service_fee_percent = self._enabled_service_fee_percent(table)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.capture_service_fee_snapshot()
        return super().save(*args, **kwargs)

    @property
    def service_fee_percent(self) -> Decimal:
        if self.channel != self.Channel.HALL:
            return Decimal('0')
        return sum(
            (
                self.restaurant_service_fee_percent or Decimal('0'),
                self.hall_service_fee_percent or Decimal('0'),
                self.table_service_fee_percent or Decimal('0'),
            ),
            Decimal('0'),
        )

    @property
    def service_fee_enabled(self) -> bool:
        return self.service_fee_percent > 0

    def get_service_fee_components(self) -> list[dict]:
        if self.channel != self.Channel.HALL:
            return []
        table_session = self.table_session if self.table_session_id else None
        hall = getattr(table_session, 'hall', None)
        table = getattr(table_session, 'table', None)
        component_specs = (
            ('restaurant', self.restaurant_service_fee_percent, self.restaurant),
            ('hall', self.hall_service_fee_percent, hall),
            ('table', self.table_service_fee_percent, table),
        )
        components = []
        for scope, percent, source in component_specs:
            percent = percent or Decimal('0')
            if percent <= 0:
                continue
            json_percent = int(percent) if percent == percent.to_integral_value() else float(percent)
            components.append(
                {
                    'scope': scope,
                    'source_name': getattr(source, 'name', ''),
                    'percent': json_percent,
                    'amount': self.calculate_service_fee_amount(int(self.subtotal or 0), percent),
                }
            )
        return components

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
        if self.channel == self.Channel.HALL:
            service_fee = sum(
                self.calculate_service_fee_amount(subtotal, percent)
                for percent in (
                    self.restaurant_service_fee_percent,
                    self.hall_service_fee_percent,
                    self.table_service_fee_percent,
                )
            )

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
