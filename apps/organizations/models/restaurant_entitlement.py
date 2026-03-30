from django.db import models

from common.models import BaseModel


class RestaurantEntitlement(BaseModel):
    restaurant = models.OneToOneField(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='entitlement',
    )
    tariff = models.ForeignKey(
        'organizations.Tariff',
        on_delete=models.SET_NULL,
        related_name='restaurant_entitlements',
        null=True,
        blank=True,
    )
    is_custom = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    starts_on = models.DateField(null=True, blank=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    yearly_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    permissions = models.ManyToManyField('accounts.Permission', blank=True, related_name='restaurant_entitlements')
    allowed_roles = models.ManyToManyField('accounts.Role', blank=True, related_name='restaurant_entitlements')
    operational_settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('restaurant__name',)

    def __str__(self):
        return f'Entitlement for {self.restaurant}'

    def get_effective_permission_codes(self) -> set[str]:
        tariff_codes = set(self.tariff.permissions.values_list('code', flat=True)) if self.tariff_id else set()
        override_codes = set(self.permissions.values_list('code', flat=True))
        return tariff_codes | override_codes

    def get_effective_role_codes(self) -> set[str]:
        tariff_codes = set(self.tariff.allowed_roles.values_list('code', flat=True)) if self.tariff_id else set()
        override_codes = set(self.allowed_roles.values_list('code', flat=True))
        return tariff_codes | override_codes
