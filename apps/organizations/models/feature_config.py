from django.db import models

from common.models import BaseModel


class FeatureConfig(BaseModel):
    class OrderEntryMode(models.TextChoices):
        HALL = 'hall', 'Hall'
        CASHIER_BUILDER = 'cashier_builder', 'Cashier builder'

    class KitchenMode(models.TextChoices):
        DISPLAY = 'display', 'Display'
        PRINTER = 'printer', 'Printer'
        BOTH = 'both', 'Both'

    restaurant = models.OneToOneField('organizations.Restaurant', on_delete=models.CASCADE, related_name='feature_config')
    hall_enabled = models.BooleanField(default=True)
    kitchen_enabled = models.BooleanField(default=True)
    cashier_enabled = models.BooleanField(default=True)
    owner_dashboard_enabled = models.BooleanField(default=True)
    order_entry_mode = models.CharField(
        max_length=32,
        choices=OrderEntryMode.choices,
        default=OrderEntryMode.HALL,
    )
    kitchen_mode = models.CharField(max_length=20, choices=KitchenMode.choices, default=KitchenMode.DISPLAY)
    enabled_modules = models.JSONField(default=list, blank=True)
    enabled_roles = models.JSONField(default=list, blank=True)
    entitlement_overrides = models.JSONField(default=dict, blank=True)
