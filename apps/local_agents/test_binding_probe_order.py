from django.test import TestCase

from apps.integrations.models import IntegrationConfig
from apps.local_agents.sync import _device_bindings
from apps.restaurants.models import CashDesk, Restaurant


class DeviceBindingsProbeOrderTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Printer probe order')

    def printer(self, name, *, enabled=True, restaurant=None):
        return IntegrationConfig.objects.create(
            restaurant=restaurant or self.restaurant,
            name=name,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            is_enabled=enabled,
            settings={'connection_type': 'system_printer', 'printer_name': name},
        )

    def test_cashier_printer_precedes_older_kitchen_targets_without_dropping_them(self):
        kitchen = self.printer('Kitchen')
        grill = self.printer('Grill')
        cashier = self.printer('Cashier')
        desk = CashDesk.objects.create(
            restaurant=self.restaurant, name='Cash desk', printer_integration=cashier,
        )

        bindings = _device_bindings(self.restaurant)

        self.assertEqual(
            [item['id'] for item in bindings['integrations']],
            [str(cashier.pk), str(kitchen.pk), str(grill.pk)],
        )
        self.assertEqual(bindings['cashDesks'][0]['id'], str(desk.pk))
        self.assertEqual(bindings['cashDesks'][0]['printerIntegrationId'], str(cashier.pk))
        self.assertEqual(bindings['integrations'][0]['settings']['printer_name'], 'Cashier')

    def test_inactive_cash_desk_does_not_take_probe_priority(self):
        kitchen = self.printer('Kitchen')
        retired = self.printer('Retired cash desk')
        CashDesk.objects.create(
            restaurant=self.restaurant, name='Retired', printer_integration=retired,
            is_active=False,
        )

        bindings = _device_bindings(self.restaurant)

        self.assertEqual(bindings['cashDesks'], [])
        self.assertEqual(
            [item['id'] for item in bindings['integrations']],
            [str(kitchen.pk), str(retired.pk)],
        )

    def test_priority_does_not_enable_disabled_or_cross_restaurant_integrations(self):
        local = self.printer('Local')
        disabled = self.printer('Disabled', enabled=False)
        CashDesk.objects.create(
            restaurant=self.restaurant, name='Disabled printer', printer_integration=disabled,
        )
        other = Restaurant.objects.create(name='Other restaurant')
        foreign = self.printer('Foreign', restaurant=other)
        CashDesk.objects.create(restaurant=other, name='Other cash desk', printer_integration=foreign)

        bindings = _device_bindings(self.restaurant)

        self.assertEqual([item['id'] for item in bindings['integrations']], [str(local.pk)])
