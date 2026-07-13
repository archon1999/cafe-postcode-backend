from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


class PrintTemplatePermissionMigrationTests(TestCase):
    def test_restaurant_admin_tariffs_and_custom_entitlements_receive_printing_permissions(self):
        restaurant_admin = Role.objects.get(code='restaurant_admin')
        tariff = Tariff.objects.create(name='Legacy restaurant tariff')
        tariff.allowed_roles.add(restaurant_admin)

        restaurant = Restaurant.objects.create(name='Legacy custom restaurant')
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=restaurant,
            is_active=True,
            is_custom=True,
        )
        User.objects.create_user(
            username='legacy-restaurant-admin',
            password='secret123',
            full_name='Legacy Restaurant Admin',
            restaurant=restaurant,
            role=restaurant_admin,
        )

        migration = import_module(
            'apps.platform.migrations.0009_add_print_template_permissions_to_admin_access'
        )
        migration.add_print_template_permissions_to_admin_access(django_apps, None)

        expected_codes = {'print_templates.view', 'print_templates.create', 'print_templates.update'}
        self.assertTrue(
            expected_codes.issubset(set(tariff.permissions.values_list('code', flat=True)))
        )
        self.assertTrue(
            expected_codes.issubset(set(entitlement.permissions.values_list('code', flat=True)))
        )
        self.assertEqual(Permission.objects.filter(code__in=expected_codes).count(), 3)
