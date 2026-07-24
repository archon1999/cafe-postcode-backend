from django.test import TestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.platform.services.modifier_access import MODIFIER_PERMISSION_CODES, grant_default_modifier_access
from apps.restaurants.models import Restaurant
from apps.users.models import Role, User


class ModifierAccessPermissionTests(TestCase):
    def test_grants_modifier_permissions_to_admin_tariffs_and_custom_entitlements(self):
        admin = Role.objects.get(code='restaurant_admin')
        tariff = Tariff.objects.create(name='Legacy modifier tariff')
        tariff.allowed_roles.add(admin)

        restaurant = Restaurant.objects.create(name='Legacy custom modifier restaurant')
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=restaurant,
            is_active=True,
            is_custom=True,
        )
        User.objects.create_user(
            username='legacy-modifier-admin',
            restaurant=restaurant,
            role=admin,
        )

        grant_default_modifier_access()

        expected_codes = set(MODIFIER_PERMISSION_CODES)
        self.assertTrue(expected_codes.issubset(set(tariff.permissions.values_list('code', flat=True))))
        self.assertTrue(expected_codes.issubset(set(entitlement.permissions.values_list('code', flat=True))))
