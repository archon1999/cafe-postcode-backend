from django.db import models

from common.models import BaseModel


class RestaurantEntitlement(BaseModel):
    restaurant = models.OneToOneField(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='entitlement',
    )
    tariff = models.ForeignKey(
        'platform.Tariff',
        on_delete=models.SET_NULL,
        related_name='restaurant_entitlements',
        null=True,
        blank=True,
    )
    is_custom = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    permissions = models.ManyToManyField('users.Permission', blank=True, related_name='restaurant_entitlements')
    allowed_roles = models.ManyToManyField('users.Role', blank=True, related_name='restaurant_entitlements')

    class Meta:
        ordering = ('restaurant__name',)

    def __str__(self):
        return f'Entitlement for {self.restaurant}'

    def get_effective_permission_codes(self) -> set[str]:
        tariff_codes = (
            {permission.code for permission in self.tariff.permissions.all()}
            if self.tariff_id
            else set()
        )
        override_codes = {permission.code for permission in self.permissions.all()}
        return tariff_codes | override_codes

    def get_effective_role_codes(self) -> set[str]:
        tariff_codes = (
            {role.code for role in self.tariff.allowed_roles.all()}
            if self.tariff_id
            else set()
        )
        override_codes = {role.code for role in self.allowed_roles.all()}
        return tariff_codes | override_codes
