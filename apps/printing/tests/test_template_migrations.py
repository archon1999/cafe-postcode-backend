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

    def test_replaces_payment_line_total_with_unit_price(self):
        migration = import_module(
            'apps.printing.migrations.0012_publish_unit_prices_on_payment_receipts'
        )
        layout = {
            'blocks': [
                {
                    'type': 'items_table',
                    'columns': [
                        {'label': 'Mahsulot', 'value': '{{item.name}}'},
                        {'label': 'Soni', 'value': 'x{{item.quantity}}'},
                        {
                            'label': 'Summa',
                            'value': '{{item.lineTotal}}',
                            'format': 'money',
                        },
                    ],
                }
            ]
        }

        changed = migration.replace_payment_line_totals(layout)

        self.assertTrue(changed)
        self.assertEqual(
            layout['blocks'][0]['columns'][2]['value'],
            '{{item.unitPrice}}',
        )
