from django.db import models

from common.models import BaseModel


def default_enabled_payment_methods():
    return ['cash', 'card', 'qr']


class CashDesk(BaseModel):
    class FiscalProvider(models.TextChoices):
        FISCAL_DRIVE_SERVICE = 'fiscal-drive-service', 'FiscalDriveService'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='cash_desks')
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    enabled_payment_methods = models.JSONField(default=default_enabled_payment_methods, blank=True)
    fiscal_provider = models.CharField(
        max_length=32,
        choices=FiscalProvider.choices,
        default=FiscalProvider.FISCAL_DRIVE_SERVICE,
    )
    receipt_printer_enabled = models.BooleanField(default=True)
    terminal_id = models.CharField(max_length=120, blank=True)
    external_cashbox_id = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)
