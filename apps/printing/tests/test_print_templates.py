from copy import deepcopy
from importlib import import_module

from django.apps import apps as django_apps
from rest_framework import status
from rest_framework.test import APITestCase

from apps.printing.models import PrintTemplate, PrintTemplateVersion
from apps.printing.presets import get_preset_layout
from apps.restaurants.models import Restaurant
from apps.users.models import User


class PrintTemplateAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Restaurant One')
        cls.other_restaurant = Restaurant.objects.create(name='Restaurant Two')
        cls.superuser = User.objects.create_superuser(
            username='printing-superuser',
            password='secret123',
            full_name='Printing Superuser',
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_restaurant_creation_provisions_the_three_active_published_templates(self):
        templates = PrintTemplate.objects.filter(restaurant=self.restaurant).select_related('published_version')

        self.assertEqual(templates.count(), 3)
        self.assertSetEqual(
            set(templates.values_list('kind', flat=True)),
            {
                PrintTemplate.Kind.KITCHEN_TICKET,
                PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
                PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
            },
        )
        for template in templates:
            self.assertIsNotNone(template.published_version)
            self.assertEqual(template.published_version.status, PrintTemplateVersion.Status.PUBLISHED)
            self.assertEqual(template.published_version.revision, 1)
            self.assertEqual(template.published_version.preset_key, 'legacy_80')
            self.assertEqual(template.published_version.layout['paperWidthMm'], 80)

    def test_list_returns_only_scoped_restaurant_templates(self):
        response = self.client.get('/api/v1/admin/printing/templates/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 3)
        returned_ids = {item['id'] for item in response.data}
        own_ids = {str(value) for value in PrintTemplate.objects.filter(restaurant=self.restaurant).values_list('id', flat=True)}
        self.assertSetEqual(returned_ids, own_ids)

    def test_preset_catalog_exposes_four_packs_for_the_three_active_kinds(self):
        response = self.client.get('/api/v1/admin/printing/presets/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data['presets']), 4)
        for preset in response.data['presets']:
            self.assertSetEqual(
                set(preset['templates']),
                {
                    PrintTemplate.Kind.KITCHEN_TICKET,
                    PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
                    PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
                },
            )
        self.assertIn('variablesByKind', response.data)
        self.assertIn('sampleData', response.data)
        self.assertNotIn(PrintTemplate.Kind.ORDER_PRECHECK, response.data['variablesByKind'])
        self.assertIn('item.vat', response.data['variablesByKind'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL])
        for preset in response.data['presets']:
            for layout in preset['templates'].values():
                self.assertTrue(
                    any(
                        row.get('value') == '{{order.zoneDisplay}}'
                        for block in layout['blocks']
                        for row in block.get('rows', [])
                    )
                )
            plain_blocks = preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN]['blocks']
            plain_items = next(block for block in plain_blocks if block['type'] == 'items_table')
            self.assertTrue(plain_items['showHeaders'])
            self.assertEqual(plain_items['columns'][-1]['value'], '{{item.unitPrice}}')
            self.assertFalse(plain_items.get('showVat', False))
            self.assertFalse(
                any('totals.vat' in str(row.get('value', '')) for block in plain_blocks for row in block.get('rows', []))
            )
            fiscal_items = next(
                block
                for block in preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL]['blocks']
                if block['type'] == 'items_table'
            )
            self.assertEqual(fiscal_items['columns'][-1]['value'], '{{item.unitPrice}}')
            self.assertTrue(fiscal_items['showVat'])
            fiscal_qr = next(
                block
                for block in preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL]['blocks']
                if block['type'] == 'qr'
            )
            self.assertEqual(fiscal_qr['align'], 'center')
            self.assertEqual(fiscal_qr['qrScale'], 2)

            kitchen_blocks = preset['templates'][PrintTemplate.Kind.KITCHEN_TICKET]['blocks']
            kitchen_items = next(block for block in kitchen_blocks if block['type'] == 'items_table')
            self.assertTrue(kitchen_items['showHeaders'])
            self.assertNotIn('{{restaurant.address}}', str(kitchen_blocks))
            self.assertFalse(
                any(
                    block.get('id') in {'footer', 'footer-thanks', 'footer-appetite'}
                    for block in kitchen_blocks
                )
            )

            service_fees_index = next(
                index for index, block in enumerate(plain_blocks) if block['id'] == 'service-fees'
            )
            totals_index = next(index for index, block in enumerate(plain_blocks) if block['id'] == 'totals')
            self.assertEqual(plain_blocks[service_fees_index - 1]['type'], 'divider')
            self.assertEqual(plain_blocks[totals_index - 1]['type'], 'divider')
            self.assertLess(service_fees_index, totals_index)
            self.assertEqual(plain_blocks[totals_index]['rows'][-1]['value'], '{{totals.total}}')

    def test_create_draft_from_preset_and_publish_retires_previous_version(self):
        template = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        old_version = template.published_version

        create_response = self.client.post(
            f'/api/v1/admin/printing/templates/{template.id}/versions/',
            {'presetKey': 'legacy_80'},
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        self.assertEqual(create_response.data['status'], PrintTemplateVersion.Status.DRAFT)
        self.assertEqual(create_response.data['revision'], 2)

        version_id = create_response.data['id']
        publish_response = self.client.post(
            f'/api/v1/admin/printing/templates/{template.id}/versions/{version_id}/publish/',
            {},
            format='json',
        )

        self.assertEqual(publish_response.status_code, status.HTTP_200_OK, publish_response.data)
        template.refresh_from_db()
        old_version.refresh_from_db()
        self.assertEqual(str(template.published_version_id), version_id)
        self.assertEqual(old_version.status, PrintTemplateVersion.Status.RETIRED)
        self.assertEqual(template.published_version.status, PrintTemplateVersion.Status.PUBLISHED)

    def test_zone_location_migration_preserves_layout_and_publishes_a_new_revision(self):
        template = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        previous = template.published_version
        legacy_layout = deepcopy(previous.layout)
        for block in legacy_layout['blocks']:
            if isinstance(block.get('rows'), list):
                block['rows'] = [
                    row for row in block['rows'] if row.get('value') != '{{order.zoneDisplay}}'
                ]
        previous.layout = legacy_layout
        previous.save(update_fields=('layout', 'updated_at'))
        self.assertNotIn('{{order.zoneDisplay}}', str(previous.layout))

        migration = import_module('apps.printing.migrations.0007_publish_order_zone_location')
        migration.publish_order_zone_location(django_apps, None)

        template.refresh_from_db()
        previous.refresh_from_db()
        self.assertNotEqual(template.published_version_id, previous.id)
        self.assertEqual(previous.status, PrintTemplateVersion.Status.RETIRED)
        self.assertIn('{{order.zoneDisplay}}', str(template.published_version.layout))

    def test_unification_migration_updates_published_layouts_and_retires_precheck(self):
        kitchen = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.KITCHEN_TICKET,
        )
        kitchen_previous = kitchen.published_version
        kitchen_layout = deepcopy(kitchen_previous.layout)
        kitchen_items = next(block for block in kitchen_layout['blocks'] if block['type'] == 'items_table')
        kitchen_items.pop('showHeaders', None)
        kitchen_layout['blocks'][-2:-2] = [
            {'id': 'footer-divider', 'type': 'divider'},
            {'id': 'footer-thanks', 'type': 'text', 'text': 'Buyurtmangiz uchun rahmat!'},
        ]
        kitchen_layout['blocks'].insert(
            2,
            {
                'id': 'restaurant-details',
                'type': 'metadata',
                'rows': [{'label': 'Manzil', 'value': '{{restaurant.address}}'}],
            },
        )
        kitchen_previous.layout = kitchen_layout
        kitchen_previous.save(update_fields=('layout', 'updated_at'))

        plain = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        plain_previous = plain.published_version
        plain_layout = deepcopy(plain_previous.layout)
        service_fees = next(block for block in plain_layout['blocks'] if block['id'] == 'service-fees')
        totals = next(block for block in plain_layout['blocks'] if block['id'] == 'totals')
        totals['rows'][-1:-1] = service_fees['rows']
        plain_layout['blocks'] = [
            block
            for block in plain_layout['blocks']
            if block['id'] not in {'service-fees-divider', 'service-fees', 'totals-divider'}
        ]
        totals_index = plain_layout['blocks'].index(totals)
        plain_layout['blocks'].insert(totals_index, {'id': 'total-top-divider', 'type': 'divider'})
        plain_previous.layout = plain_layout
        plain_previous.save(update_fields=('layout', 'updated_at'))

        precheck = PrintTemplate.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.ORDER_PRECHECK,
        )
        precheck_version = PrintTemplateVersion.objects.create(
            template=precheck,
            revision=1,
            status=PrintTemplateVersion.Status.PUBLISHED,
            preset_key='legacy_80',
            layout=get_preset_layout('legacy_80', PrintTemplate.Kind.ORDER_PRECHECK),
        )
        precheck.published_version = precheck_version
        precheck.save(update_fields=('published_version', 'updated_at'))

        migration = import_module('apps.printing.migrations.0010_unify_receipt_templates')
        migration.unify_receipt_templates(django_apps, None)

        kitchen.refresh_from_db()
        kitchen_previous.refresh_from_db()
        kitchen_blocks = kitchen.published_version.layout['blocks']
        self.assertEqual(kitchen_previous.status, PrintTemplateVersion.Status.RETIRED)
        self.assertTrue(next(block for block in kitchen_blocks if block['type'] == 'items_table')['showHeaders'])
        self.assertNotIn('{{restaurant.address}}', str(kitchen_blocks))
        self.assertNotIn('Buyurtmangiz uchun rahmat!', str(kitchen_blocks))

        plain.refresh_from_db()
        plain_blocks = plain.published_version.layout['blocks']
        service_index = next(index for index, block in enumerate(plain_blocks) if block['id'] == 'service-fees')
        totals_index = next(index for index, block in enumerate(plain_blocks) if block['id'] == 'totals')
        self.assertLess(service_index, totals_index)
        self.assertEqual(plain_blocks[totals_index - 1]['type'], 'divider')
        self.assertEqual(plain_blocks[totals_index]['rows'][-1]['value'], '{{totals.total}}')

        precheck.refresh_from_db()
        precheck_version.refresh_from_db()
        self.assertIsNone(precheck.published_version)
        self.assertEqual(precheck_version.status, PrintTemplateVersion.Status.RETIRED)

    def test_invalid_layout_is_rejected_before_a_draft_is_created(self):
        template = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
        )

        response = self.client.post(
            f'/api/v1/admin/printing/templates/{template.id}/versions/',
            {
                'layout': {
                    'schemaVersion': 1,
                    'paperWidthMm': 80,
                    'blocks': [{'id': 'unsafe', 'type': 'text', 'text': '{{fiscal.apiKey}}'}],
                }
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('blocks', response.data)
        self.assertIn('variables', response.data)
        self.assertEqual(template.versions.count(), 1)

    def test_58_mm_layout_is_rejected(self):
        template = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        layout = dict(template.published_version.layout)
        layout['paperWidthMm'] = 58

        response = self.client.post(
            f'/api/v1/admin/printing/templates/{template.id}/versions/',
            {'layout': layout},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('paperWidthMm', response.data)

    def test_other_restaurant_template_is_not_addressable(self):
        foreign_template = PrintTemplate.objects.filter(restaurant=self.other_restaurant).first()

        response = self.client.get(f'/api/v1/admin/printing/templates/{foreign_template.id}/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

    def test_nested_camel_case_layout_survives_request_parser_underscoreization(self):
        template = PrintTemplate.objects.get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
        )
        layout = dict(template.published_version.layout)

        response = self.client.post(
            f'/api/v1/admin/printing/templates/{template.id}/versions/',
            {'layout': layout, 'presetKey': 'legacy_80'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        saved_layout = template.versions.get(id=response.data['id']).layout
        self.assertEqual(saved_layout['schemaVersion'], 1)
        self.assertEqual(saved_layout['paperWidthMm'], 80)
        items = next(block for block in saved_layout['blocks'] if block['type'] == 'items_table')
        qr = next(block for block in saved_layout['blocks'] if block['type'] == 'qr')
        self.assertTrue(items['showVat'])
        self.assertEqual(qr['qrScale'], 2)
