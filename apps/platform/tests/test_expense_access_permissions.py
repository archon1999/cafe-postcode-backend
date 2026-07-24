from django.test import TestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.platform.services.expense_access import (
    ADMIN_EXPENSE_PERMISSION_CODES,
    POS_EXPENSE_PERMISSION_CODES,
    grant_default_expense_access,
)
from apps.restaurants.models import Restaurant
from apps.users.models import Role, User


class ExpenseAccessPermissionTests(TestCase):
    def test_grants_expense_permissions_to_manager_and_admin_access(self):
        manager = Role.objects.get(code='manager')
        admin = Role.objects.get(code='restaurant_admin')
        tariff = Tariff.objects.create(name='Legacy expense tariff')
        tariff.allowed_roles.add(manager, admin)

        restaurant = Restaurant.objects.create(name='Legacy custom expense restaurant')
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=restaurant,
            is_active=True,
            is_custom=True,
        )
        User.objects.create_user(
            username='legacy-expense-manager',
            restaurant=restaurant,
            role=manager,
        )
        User.objects.create_user(
            username='legacy-expense-admin',
            restaurant=restaurant,
            role=admin,
        )

        grant_default_expense_access()

        tariff_codes = set(tariff.permissions.values_list('code', flat=True))
        entitlement_codes = set(entitlement.permissions.values_list('code', flat=True))
        expected_codes = set(POS_EXPENSE_PERMISSION_CODES) | set(ADMIN_EXPENSE_PERMISSION_CODES)
        self.assertTrue(expected_codes.issubset(tariff_codes))
        self.assertTrue(expected_codes.issubset(entitlement_codes))
