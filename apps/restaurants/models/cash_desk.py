from django.db import models

from common.models import BaseModel


def default_enabled_payment_methods():
    return ['cash', 'card', 'mixed']


class CashDesk(BaseModel):
    class FiscalProvider(models.TextChoices):
        FISCAL_DRIVE_SERVICE = 'fiscal-drive-service', 'FiscalDriveService'
        UNIKASSA = 'unikassa', 'Unikassa'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='cash_desks')
    fiscal_integration = models.ForeignKey(
        'integrations.IntegrationConfig',
        on_delete=models.SET_NULL,
        related_name='cash_desks',
        blank=True,
        null=True,
    )
    payment_integration = models.ForeignKey(
        'integrations.IntegrationConfig',
        on_delete=models.SET_NULL,
        related_name='payment_cash_desks',
        blank=True,
        null=True,
    )
    printer_integration = models.ForeignKey(
        'integrations.IntegrationConfig',
        on_delete=models.SET_NULL,
        related_name='printer_cash_desks',
        blank=True,
        null=True,
    )
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
