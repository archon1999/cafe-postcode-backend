from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from common.api.permissions import (
    POS_HALLS_VIEW_PERMISSION,
    POS_KITCHEN_ORDERS_UPDATE_PERMISSION,
    POS_KITCHEN_ORDERS_VIEW_PERMISSION,
    POS_OPEN_CHECKS_VIEW_PERMISSION,
    POS_PAYMENTS_CREATE_PERMISSION,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
)


class FeatureGateService:
    def ensure_restaurant_access(self, *, restaurant):
        if not getattr(restaurant, 'is_active', False):
            raise ValidationError({'detail': _('Restaurant is inactive.')})

        entitlement = getattr(restaurant, 'entitlement', None)
        if entitlement is None or not entitlement.is_active:
            raise ValidationError({'detail': _('Restaurant access is not activated.')})
        return entitlement

    def ensure_capability_universe(self, *, restaurant, permission_codes: tuple[str, ...], message: str):
        entitlement = self.ensure_restaurant_access(restaurant=restaurant)
        if permission_codes:
            effective_permission_codes = entitlement.get_effective_permission_codes()
            if not any(code in effective_permission_codes for code in permission_codes):
                raise ValidationError({'detail': _(message)})
        return entitlement

    def ensure_kitchen_access(self, *, restaurant, interactive: bool = False):
        return self.ensure_capability_universe(
            restaurant=restaurant,
            permission_codes=('kitchen_queue.view', POS_KITCHEN_ORDERS_VIEW_PERMISSION, POS_KITCHEN_ORDERS_UPDATE_PERMISSION),
            message='Kitchen access is not available for this restaurant.',
        )

    def ensure_owner_dashboard_access(self, *, restaurant):
        return self.ensure_capability_universe(
            restaurant=restaurant,
            permission_codes=('dashboard.view',),
            message='Owner dashboard access is not available for this restaurant.',
        )

    def ensure_cashier_access(self, *, restaurant):
        return self.ensure_capability_universe(
            restaurant=restaurant,
            permission_codes=('open_checks.view', 'payments.create', POS_OPEN_CHECKS_VIEW_PERMISSION, POS_PAYMENTS_CREATE_PERMISSION, POS_TAKEAWAY_MENU_VIEW_PERMISSION),
            message='Cashier access is not available for this restaurant.',
        )

    def ensure_hall_access(self, *, restaurant):
        return self.ensure_capability_universe(
            restaurant=restaurant,
            permission_codes=('catalog_menu.view', POS_HALLS_VIEW_PERMISSION, POS_TABLES_MANAGE_PERMISSION),
            message='Hall access is not available for this restaurant.',
        )
