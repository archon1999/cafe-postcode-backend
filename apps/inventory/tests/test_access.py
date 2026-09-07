from django.test import TestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.platform.services.inventory_access import grant_default_inventory_access, INVENTORY_PERMISSION_CODES
from apps.restaurants.models import Restaurant
from apps.users.models import Role, User


class InventoryEntitlementTests(TestCase):
    def test_tariff_with_admin_role_gets_inventory_capabilities(self):
        role = Role.objects.get(code='restaurant_admin')
        tariff = Tariff.objects.create(name='Admin-capable tariff')
        tariff.allowed_roles.add(role)
        grant_default_inventory_access()
        self.assertTrue(set(INVENTORY_PERMISSION_CODES) <= set(tariff.permissions.values_list('code', flat=True)))

    def test_custom_entitlement_admin_without_tariff_is_granted_idempotently(self):
        restaurant = Restaurant.objects.create(name='Custom contract restaurant')
        role = Role.objects.get(code='restaurant_admin')
        user = User.objects.create_user('custom-inventory-admin', restaurant=restaurant, role=role)
        entitlement = RestaurantEntitlement.objects.create(restaurant=restaurant, is_custom=True, is_active=True)
        grant_default_inventory_access()
        grant_default_inventory_access()
        self.assertTrue(set(INVENTORY_PERMISSION_CODES) <= set(entitlement.permissions.values_list('code', flat=True)))
        self.assertTrue(set(INVENTORY_PERMISSION_CODES) <= set(user.permission_codes))

    def test_unrelated_tariff_is_not_granted_cost_or_write_permissions(self):
        tariff = Tariff.objects.create(name='Waiter-only tariff')
        tariff.allowed_roles.add(Role.objects.get(code='waiter'))
        grant_default_inventory_access()
        self.assertFalse(tariff.permissions.filter(code__in=INVENTORY_PERMISSION_CODES).exists())
