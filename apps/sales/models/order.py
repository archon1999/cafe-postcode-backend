from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from common.indexes import scoped_status_index, scoped_timestamp_index
from common.models import BaseModel
from common.service_fees import (
    ServiceFeeMode,
    build_service_fee_snapshot,
    calculate_percentage_service_fee,
    calculate_service_fee_components,
    normalize_service_fee_snapshot,
    service_fee_billable_minutes,
    service_fee_percent_total,
)


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
    service_fee_snapshot = models.JSONField(default=list, blank=True)
    service_fee_started_at = models.DateTimeField(null=True, blank=True)
    service_fee_frozen_at = models.DateTimeField(null=True, blank=True)
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
        return calculate_percentage_service_fee(subtotal=subtotal, percent=percent)

    def _legacy_service_fee_snapshot(self) -> list[dict]:
        if self.channel != self.Channel.HALL:
            return []
        table_session = self.table_session if self.table_session_id else None
        hall = getattr(table_session, 'hall', None)
        table = getattr(table_session, 'table', None)
        source_specs = (
            ('restaurant', self.restaurant_service_fee_percent, self.restaurant),
            ('hall', self.hall_service_fee_percent, hall),
            ('table', self.table_service_fee_percent, table),
        )
        return [
            {
                'scope': scope,
                'source_name': getattr(source, 'name', ''),
                'mode': ServiceFeeMode.PERCENTAGE,
                'percent': int(percent) if percent == percent.to_integral_value() else float(percent),
            }
            for scope, raw_percent, source in source_specs
            if (percent := Decimal(str(raw_percent or 0))) > 0
        ]

    def get_service_fee_snapshot(self) -> list[dict]:
        snapshot = normalize_service_fee_snapshot(self.service_fee_snapshot)
        if any(component['mode'] == ServiceFeeMode.HOURLY for component in snapshot):
            return snapshot
        legacy_snapshot = self._legacy_service_fee_snapshot()
        return legacy_snapshot if legacy_snapshot else snapshot

    def capture_service_fee_snapshot(self):
        if self.channel != self.Channel.HALL:
            self.restaurant_service_fee_percent = Decimal('0')
            self.hall_service_fee_percent = Decimal('0')
            self.table_service_fee_percent = Decimal('0')
            self.service_fee_snapshot = []
            self.service_fee_started_at = None
            self.service_fee_frozen_at = None
            return

        snapshot = []
        if self.table_session_id:
            snapshot = normalize_service_fee_snapshot(self.table_session.service_fee_snapshot)
            if not snapshot:
                snapshot = build_service_fee_snapshot(
                    restaurant=self.restaurant,
                    hall=self.table_session.hall,
                    table=self.table_session.table,
                )
            self.service_fee_started_at = self.table_session.opened_at
        else:
            snapshot = build_service_fee_snapshot(restaurant=self.restaurant)
            self.service_fee_started_at = timezone.now()
        self.service_fee_snapshot = snapshot
        percentage_by_scope = {
            component['scope']: Decimal(str(component.get('percent') or 0))
            for component in snapshot
            if component['mode'] == ServiceFeeMode.PERCENTAGE
        }
        self.restaurant_service_fee_percent = percentage_by_scope.get('restaurant', Decimal('0'))
        self.hall_service_fee_percent = percentage_by_scope.get('hall', Decimal('0'))
        self.table_service_fee_percent = percentage_by_scope.get('table', Decimal('0'))

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.capture_service_fee_snapshot()
        return super().save(*args, **kwargs)

    @property
    def service_fee_percent(self) -> Decimal:
        if self.channel != self.Channel.HALL:
            return Decimal('0')
        return service_fee_percent_total(self.get_service_fee_snapshot())

    @property
    def service_fee_enabled(self) -> bool:
        return bool(self.channel == self.Channel.HALL and self.get_service_fee_snapshot())

    @property
    def has_hourly_service_fee(self) -> bool:
        return any(
            component['mode'] == ServiceFeeMode.HOURLY
            for component in self.get_service_fee_snapshot()
        )

    def get_service_fee_billable_minutes(self, *, as_of=None) -> int:
        if not self.has_hourly_service_fee:
            return 0
        return service_fee_billable_minutes(
            started_at=self.service_fee_started_at,
            ended_at=self.service_fee_frozen_at or as_of,
        )

    def get_service_fee_components(self, *, as_of=None) -> list[dict]:
        if self.channel != self.Channel.HALL:
            return []
        return calculate_service_fee_components(
            snapshot=self.get_service_fee_snapshot(),
            subtotal=int(self.subtotal or 0),
            started_at=self.service_fee_started_at,
            ended_at=self.service_fee_frozen_at or as_of,
        )

    def get_service_fee_amount(self, *, as_of=None) -> int:
        return sum(
            int(component.get('amount') or 0)
            for component in self.get_service_fee_components(as_of=as_of)
        )

    def get_calculated_total(self, *, as_of=None) -> int:
        return int(self.subtotal or 0) + self.get_service_fee_amount(as_of=as_of)

    def get_total(self, *, as_of=None) -> int:
        if self.total_override is not None:
            return int(self.total_override)
        return self.get_calculated_total(as_of=as_of)

    def freeze_service_fee(self, *, at=None):
        if not self.has_hourly_service_fee or self.service_fee_frozen_at is not None:
            return
        self.service_fee_frozen_at = at or timezone.now()
        self.recalculate_totals(preserve_override=True, as_of=self.service_fee_frozen_at)

    @property
    def branch(self):
        return self.restaurant

    @branch.setter
    def branch(self, value):
        self.restaurant = value

    def recalculate_totals(self, *, preserve_override=False, as_of=None):
        from .order_item import OrderItem

        active_items = self.items.exclude(status=OrderItem.Status.CANCELLED)
        subtotal = active_items.aggregate(total=models.Sum('line_total')).get('total') or 0
        service_fee = 0
        if self.channel == self.Channel.HALL:
            service_fee = sum(
                int(component.get('amount') or 0)
                for component in calculate_service_fee_components(
                    snapshot=self.get_service_fee_snapshot(),
                    subtotal=int(subtotal or 0),
                    started_at=self.service_fee_started_at,
                    ended_at=self.service_fee_frozen_at or as_of,
                )
            )

        calculated_total = subtotal + service_fee
        self.subtotal = subtotal
        self.calculated_total = calculated_total
        if preserve_override and self.total_override is not None:
            self.total = self.total_override
            update_fields = ['subtotal', 'calculated_total', 'total', 'service_fee_frozen_at', 'updated_at']
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
                'service_fee_frozen_at',
                'updated_at',
            ]
        self.save(update_fields=update_fields)
