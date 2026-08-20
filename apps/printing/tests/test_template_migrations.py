from importlib import import_module

from django.test import SimpleTestCase


class PaymentTemplateMigrationTests(SimpleTestCase):
    def test_removes_waiter_alias_only_when_real_cashier_row_exists(self):
        migration = import_module(
            'apps.printing.migrations.0011_remove_legacy_cashier_alias'
        )
        layout = {
            'blocks': [
                {
                    'type': 'metadata',
                    'rows': [
                        {'label': 'Kassir', 'value': '{{order.waiter}}'},
                        {'label': 'Kassir', 'value': '{{order.cashier}}'},
                        {'label': 'Stol', 'value': '{{order.table}}'},
                    ],
                }
            ]
        }

        changed = migration.remove_legacy_cashier_alias(layout)

        self.assertTrue(changed)
        self.assertEqual(
            layout['blocks'][0]['rows'],
            [
                {'label': 'Kassir', 'value': '{{order.cashier}}'},
                {'label': 'Stol', 'value': '{{order.table}}'},
            ],
        )

    def test_keeps_legacy_alias_when_no_cashier_row_exists(self):
        migration = import_module(
            'apps.printing.migrations.0011_remove_legacy_cashier_alias'
        )
        layout = {
            'blocks': [
                {
                    'type': 'metadata',
                    'rows': [
                        {'label': 'Kassir', 'value': '{{order.waiter}}'},
                    ],
                }
            ]
        }

        changed = migration.remove_legacy_cashier_alias(layout)

        self.assertFalse(changed)
        self.assertEqual(
            layout['blocks'][0]['rows'],
            [{'label': 'Kassir', 'value': '{{order.waiter}}'}],
        )
