from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.platform.models import Tariff
from apps.users.models import Role


class ShiftViewAccessPermissionTests(TestCase):
    def test_manager_tariffs_receive_cash_shift_view_permission(self):
        manager = Role.objects.get(code='manager')
        tariff = Tariff.objects.create(name='Legacy manager tariff')
        tariff.allowed_roles.add(manager)

        migration = import_module(
            'apps.platform.migrations.0013_add_cash_shift_view_permission_to_manager_tariffs'
        )
        migration.add_cash_shift_view_permission_to_manager_tariffs(django_apps, None)

        self.assertTrue(tariff.permissions.filter(code='pos_cash_shift.view').exists())
