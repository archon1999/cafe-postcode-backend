from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import SimpleTestCase, TestCase


class PaymentTemplateMigrationTests(SimpleTestCase):
    def test_formula_labels_upgrade_without_empty_parentheses_or_layout_changes(self):
        migration = import_module('apps.printing.migrations.0015_publish_service_fee_labels')
        layout = {'blocks': [{'type': 'totals', 'rows': [
            {'label': 'STOL XIZMATI ({{totals.tableServiceFeeRateLabel}})',
             'value': '{{totals.tableServiceFee}}', 'bold': True},
            {'label': 'Jami', 'value': '{{totals.total}}'},
        ]}]}
        self.assertTrue(migration.replace_service_fee_labels(layout))
        self.assertEqual(layout['blocks'][0]['rows'], [
            {'label': '{{totals.tableServiceFeeLabel}}', 'value': '{{totals.tableServiceFee}}', 'bold': True},
            {'label': 'Jami', 'value': '{{totals.total}}'},
        ])
        self.assertFalse(migration.replace_service_fee_labels(layout))

    def test_replaces_percentage_tokens_with_service_fee_rate_labels(self):
        migration = import_module(
            'apps.printing.migrations.0013_publish_service_fee_rate_labels'
        )
        layout = {
            'blocks': [
                {
                    'type': 'totals',
                    'rows': [
                        {
                            'label': 'Restoran ({{totals.restaurantServiceFeePercent}}%)',
                            'value': '{{totals.restaurantServiceFee}}',
                        },
                        {'label': 'Jami', 'value': '{{totals.total}}'},
                    ],
                }
            ]
        }

        changed = migration.replace_service_fee_rate_labels(layout)

        self.assertTrue(changed)
        self.assertEqual(
            layout['blocks'][0]['rows'][0]['label'],
            'Restoran ({{totals.restaurantServiceFeeRateLabel}})',
        )

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


class ServiceFeeReceiptRollbackTests(TestCase):
    def test_modified_layout_blocks_reversal_before_any_template_is_changed(self):
        from apps.printing.models import PrintTemplate, PrintTemplateVersion
        from apps.restaurants.models import Restaurant

        migration = import_module('apps.printing.migrations.0015_publish_service_fee_labels')
        restaurant = Restaurant.objects.create(name='Receipt rollback')
        templates = []
        for kind in ('order_precheck', 'payment_receipt_plain', 'payment_receipt_fiscal'):
            template, _ = PrintTemplate.objects.get_or_create(restaurant=restaurant, kind=kind)
            revision = (template.versions.order_by('-revision').values_list('revision', flat=True).first() or 0) + 1
            version = PrintTemplateVersion.objects.create(template=template, revision=revision, status='published',
                layout={'blocks': [{'rows': [{'label': 'Service ({{totals.tableServiceFeeRateLabel}})',
                                            'value': '{{totals.tableServiceFee}}'}]}]})
            template.published_version = version
            template.save()
            templates.append(template)
        migration.publish_service_fee_labels(apps, SimpleNamespace(connection=connection))
        for template in templates:
            template.refresh_from_db()
        expected_ids = [template.published_version_id for template in templates]
        version_count = PrintTemplateVersion.objects.count()
        edited = templates[1].published_version
        edited.layout['blocks'][0]['rows'].append({'label': 'Custom footer', 'value': 'Retain this edit'})
        edited.save(update_fields=['layout'])
        with self.assertRaisesRegex(RuntimeError, 'was edited'):
            migration.restore_service_fee_labels(apps, SimpleNamespace(connection=connection))
        for template, expected_id in zip(templates, expected_ids):
            template.refresh_from_db()
            self.assertEqual(template.published_version_id, expected_id)
        self.assertEqual(PrintTemplateVersion.objects.count(), version_count)
