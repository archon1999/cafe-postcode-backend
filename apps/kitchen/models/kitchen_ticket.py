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
    dispatch_number = models.PositiveIntegerField(default=1)
    print_document = models.ForeignKey(
        'printing.PrintDocument',
        on_delete=models.PROTECT,
        related_name='kitchen_tickets',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    routed_via = models.CharField(max_length=20, choices=RouteMode.choices, default=RouteMode.DISPLAY)
    is_printed = models.BooleanField(default=False)
    printed_payload = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    handed_off_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('order', 'prep_station', 'dispatch_number'),
                name='kitchen_ticket_order_station_dispatch_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['restaurant', 'status', 'created_at'], name='kt_rest_status_created_idx'),
            models.Index(fields=['restaurant', 'status', 'completed_at'], name='kt_rest_status_done_idx'),
        ]


class KitchenTicketLine(BaseModel):
    ticket = models.ForeignKey(
        KitchenTicket,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    order_item = models.OneToOneField(
        'sales.OrderItem',
        on_delete=models.PROTECT,
        related_name='kitchen_ticket_line',
    )

    class Meta:
        ordering = ('created_at',)
        indexes = [
            models.Index(fields=('ticket', 'created_at'), name='kt_line_ticket_created_idx'),
        ]
