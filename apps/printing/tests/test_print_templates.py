from rest_framework import status
from rest_framework.test import APITestCase

from apps.printing.models import PrintTemplate, PrintTemplateVersion
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

    def test_restaurant_creation_provisions_exactly_three_published_templates(self):
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

    def test_preset_catalog_exposes_four_packs_variables_and_sample_data(self):
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
        self.assertIn('item.vat', response.data['variablesByKind'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL])
        for preset in response.data['presets']:
            plain_blocks = preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN]['blocks']
            plain_items = next(block for block in plain_blocks if block['type'] == 'items_table')
            self.assertFalse(plain_items.get('showVat', False))
            self.assertFalse(
                any('totals.vat' in str(row.get('value', '')) for block in plain_blocks for row in block.get('rows', []))
            )
            fiscal_items = next(
                block
                for block in preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL]['blocks']
                if block['type'] == 'items_table'
            )
            self.assertTrue(fiscal_items['showVat'])
            fiscal_qr = next(
                block
                for block in preset['templates'][PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL]['blocks']
                if block['type'] == 'qr'
            )
            self.assertEqual(fiscal_qr['align'], 'center')
            self.assertEqual(fiscal_qr['qrScale'], 2)

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
