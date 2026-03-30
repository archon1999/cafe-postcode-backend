from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.organizations.models import FeatureConfig


class FeatureGateService:
    def get_feature_config(self, *, restaurant):
        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        return feature_config

    def ensure_restaurant_access(self, *, restaurant):
        if not getattr(restaurant, 'is_active', False):
            raise ValidationError({'detail': _('Restaurant is inactive.')})

        entitlement = getattr(restaurant, 'entitlement', None)
        if entitlement is None or not entitlement.is_active:
            raise ValidationError({'detail': _('Restaurant access is not activated.')})
        return entitlement

    def ensure_kitchen_access(self, *, restaurant, interactive: bool = False):
        self.ensure_restaurant_access(restaurant=restaurant)
        feature_config = self.get_feature_config(restaurant=restaurant)
        if not feature_config.kitchen_enabled:
            raise ValidationError({'detail': _('Kitchen module is disabled for this restaurant.')})
        if interactive and feature_config.kitchen_mode == feature_config.KitchenMode.PRINTER:
            raise ValidationError({'detail': _('Kitchen display actions are disabled in printer mode.')})
        return feature_config

    def ensure_owner_dashboard_access(self, *, restaurant):
        self.ensure_restaurant_access(restaurant=restaurant)
        feature_config = self.get_feature_config(restaurant=restaurant)
        if not feature_config.owner_dashboard_enabled:
            raise ValidationError({'detail': _('Owner dashboard is disabled for this restaurant.')})
        return feature_config

    def ensure_cashier_access(self, *, restaurant):
        self.ensure_restaurant_access(restaurant=restaurant)
        feature_config = self.get_feature_config(restaurant=restaurant)
        if not feature_config.cashier_enabled:
            raise ValidationError({'detail': _('Cashier module is disabled for this restaurant.')})
        return feature_config

    def ensure_hall_access(self, *, restaurant):
        self.ensure_restaurant_access(restaurant=restaurant)
        feature_config = self.get_feature_config(restaurant=restaurant)
        if not feature_config.hall_enabled:
            raise ValidationError({'detail': _('Hall module is disabled for this restaurant.')})
        return feature_config
