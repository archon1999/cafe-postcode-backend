import copy
import io
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.inventory.ai_documents import InventoryDocumentAIUnavailable, _read_model, preview_inventory_document
from apps.inventory.models import InventoryItem, StockBalance, StockDocument, StockMovement, Warehouse
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User


LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCAL_CACHE)
class InventoryDocumentPreviewTests(TestCase):
    endpoint = '/api/v1/admin/inventory/documents/ai-preview/'

    def setUp(self):
        cache.clear()
        self.restaurant = Restaurant.objects.create(name='Preview branch')
        self.other = Restaurant.objects.create(name='Other preview branch')
        self.warehouse = Warehouse.objects.create(restaurant=self.restaurant, name='Preview warehouse')
        self.foreign_warehouse = Warehouse.objects.create(restaurant=self.other, name='Foreign warehouse')
        self.potato = InventoryItem.objects.create(restaurant=self.restaurant, name='Kartoshka', base_unit='g', purchase_unit='kg', purchase_factor=1000)
        self.egg = InventoryItem.objects.create(restaurant=self.restaurant, name='Tuxum', base_unit='piece')
        self.foreign_item = InventoryItem.objects.create(restaurant=self.other, name='Maxfiy boshqa mahsulot', base_unit='g')
        self.codes = ['admin.inventory.view', 'admin.inventory.manage', 'admin.inventory.analyze', 'admin.inventory.view_cost']
        self.permissions = Permission.objects.filter(code__in=self.codes)
        self.role = Role.objects.create(code='inventory-preview-test', name='Preview test')
        self.role.permissions.set(self.permissions)
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.restaurant, is_active=True, is_custom=True)
        entitlement.permissions.set(self.permissions)
        self.user = User.objects.create_user('inventory-preview-test', restaurant=self.restaurant, role=self.role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.text = 'Kirim: Kartoshka 2 kg, narx 15000 so‘m/kg; Tuxum 10 dona, narx 1200 so‘m/dona.'
        self.payload = {
            'kind': 'receipt', 'kindEvidence': 'Kirim', 'kindSource': 'text', 'summary': 'Ikki qator topildi.', 'warnings': [],
            'rows': [self.row('Kartoshka', self.potato, '2', 'kg', '15000', 'Kartoshka 2 kg, narx 15000 so‘m/kg', 'narx 15000 so‘m/kg'),
                     self.row('Tuxum', self.egg, '10', 'dona', '1200', 'Tuxum 10 dona, narx 1200 so‘m/dona', 'narx 1200 so‘m/dona')],
        }

    def row(self, name, item, quantity, unit, cost, evidence, price_evidence=''):
        return {'sourceName': name, 'itemId': str(item.pk) if item else None, 'candidateItemIds': [], 'quantity': quantity,
                'sourceUnit': unit, 'unitCost': cost, 'unitCostEvidence': price_evidence, 'evidence': evidence, 'source': 'text', 'warnings': []}

    def counts(self):
        return tuple(model.objects.count() for model in (StockDocument, StockMovement, StockBalance, InventoryItem, Warehouse))

    @patch('apps.inventory.ai_documents._read_model')
    def test_receipt_preview_is_grounded_scoped_and_never_mutates_stock(self, model):
        model.return_value = self.payload
        before = self.counts()
        response = self.client.post(self.endpoint, {'text': self.text, 'warehouse': str(self.warehouse.pk)}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.json()
        self.assertEqual(data['mode'], 'ai_preview')
        self.assertEqual(data['kind'], 'receipt')
        self.assertTrue(data['needsReview'])
        self.assertEqual(data['warehouse'], str(self.warehouse.pk))
        self.assertEqual(data['rows'][0]['item'], str(self.potato.pk))
        self.assertEqual(data['rows'][0]['quantity'], '2')
        self.assertEqual(data['rows'][0]['inputUnit'], 'purchase')
        self.assertEqual(data['rows'][0]['unitCost'], '15000')
        self.assertEqual(data['rows'][1]['inputUnit'], 'base')
        self.assertEqual(before, self.counts())
        self.assertNotIn(self.foreign_item, model.call_args.args[1])

    @patch('apps.inventory.ai_documents._read_model')
    def test_every_permission_is_required_before_source_reaches_provider(self, model):
        for denied in self.codes:
            self.role.permissions.set(self.permissions.exclude(code=denied))
            self.client.force_authenticate(User.objects.get(pk=self.user.pk))
            response = self.client.post(self.endpoint, {'text': self.text}, format='json')
            self.assertEqual(response.status_code, 403, response.data)
        model.assert_not_called()

    @patch('apps.inventory.ai_documents._read_model')
    def test_foreign_warehouse_is_rejected_and_non_superuser_header_cannot_switch_tenant(self, model):
        response = self.client.post(self.endpoint, {'text': self.text, 'warehouse': str(self.foreign_warehouse.pk)}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        model.assert_not_called()
        model.return_value = self.payload
        response = self.client.post(self.endpoint, {'text': self.text}, format='json', HTTP_X_ADMIN_RESTAURANT_ID=str(self.other.pk))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(self.foreign_item, model.call_args.args[1])

    @patch('apps.inventory.ai_documents._read_model')
    def test_unmatched_and_foreign_ids_never_become_inventory_references(self, model):
        self.payload['rows'] = [self.row('Not in scoped stock', self.foreign_item, '2', 'kg', None, 'Not in scoped stock 2 kg')]
        model.return_value = self.payload
        before = self.counts()
        response = self.client.post(self.endpoint, {'text': 'Kirim Not in scoped stock 2 kg'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        row = response.json()['rows'][0]
        self.assertEqual(row['match'], 'unmatched')
        self.assertIsNone(row['item'])
        self.assertIsNone(row['quantity'])
        self.assertTrue(row['warnings'])
        self.assertNotIn(str(self.foreign_item.pk), json.dumps(response.json()))
        self.assertEqual(before, self.counts())

    @patch('apps.inventory.ai_documents._read_model')
    def test_ambiguous_candidates_are_existing_scoped_items_and_not_auto_selected(self, model):
        self.payload['rows'] = [self.row('Mahsulot', self.potato, '2', 'kg', None, 'Mahsulot 2 kg')]
        self.payload['rows'][0]['candidateItemIds'] = [str(self.potato.pk), str(self.egg.pk), str(self.foreign_item.pk)]
        model.return_value = self.payload
        response = self.client.post(self.endpoint, {'text': 'Kirim Mahsulot 2 kg'}, format='json')
        row = response.json()['rows'][0]
        self.assertEqual(row['match'], 'ambiguous')
        self.assertIsNone(row['item'])
        self.assertEqual({candidate['item'] for candidate in row['candidates']}, {str(self.potato.pk), str(self.egg.pk)})

    @patch('apps.inventory.ai_documents._read_model')
    def test_unproven_quantity_or_cost_is_nullable_instead_of_invented(self, model):
        self.payload['rows'][0].update(quantity='999', unitCost='888', unitCostEvidence='narx 15000 so‘m/kg')
        model.return_value = self.payload
        response = self.client.post(self.endpoint, {'text': self.text}, format='json')
        row = response.json()['rows'][0]
        self.assertIsNone(row['quantity'])
        self.assertIsNone(row['unitCost'])
        self.assertTrue(row['warnings'])

    @patch('apps.inventory.ai_documents._read_model')
    def test_missing_direction_and_source_unit_require_manual_review(self, model):
        self.payload.update(kind=None, kindEvidence='')
        self.payload['rows'] = [self.row('Kartoshka', self.potato, '2', 'kg', '15000', 'Kartoshka 2, narx 15000', 'narx 15000')]
        model.return_value = self.payload
        response = self.client.post(self.endpoint, {'text': 'Kartoshka 2, narx 15000'}, format='json')
        data = response.json()
        self.assertIsNone(data['kind'])
        self.assertIsNone(data['rows'][0]['inputUnit'])
        self.assertIsNone(data['rows'][0]['quantity'])
        self.assertTrue(data['rows'][0]['warnings'])

    @patch('apps.inventory.ai_documents._read_model')
    def test_mixed_directions_and_unproven_product_names_are_not_auto_selected(self, model):
        model.return_value = self.payload
        first = self.client.post(self.endpoint, {'text': self.text + ' Chiqim: boshqa qator.'}, format='json')
        self.assertIsNone(first.json()['kind'])
        self.assertTrue(first.json()['warnings'])
        self.payload['rows'][0].update(sourceName='Kartoshka', evidence='Tuxum 10 dona, narx 1200 so‘m/dona', quantity='10', sourceUnit='dona')
        second = self.client.post(self.endpoint, {'text': self.text}, format='json')
        self.assertIsNone(second.json()['rows'][0]['item'])
        self.assertIsNone(second.json()['rows'][0]['quantity'])

    @patch('apps.inventory.ai_documents._read_model')
    def test_line_total_is_not_invented_as_unit_cost_and_explicit_zero_is_kept(self, model):
        self.payload['rows'] = [self.row('Kartoshka', self.potato, '2', 'kg', '30000', 'Kartoshka 2 kg jami 30000', 'jami 30000')]
        model.return_value = self.payload
        first = self.client.post(self.endpoint, {'text': 'Kirim Kartoshka 2 kg jami 30000'}, format='json')
        self.assertIsNone(first.json()['rows'][0]['unitCost'])
        self.payload['rows'] = [self.row('Kartoshka', self.potato, '2', 'kg', '0', 'Kartoshka 2 kg narx 0', 'narx 0')]
        second = self.client.post(self.endpoint, {'text': 'Kirim Kartoshka 2 kg narx 0'}, format='json')
        self.assertEqual(second.json()['rows'][0]['unitCost'], '0')

    @patch('apps.inventory.ai_documents._read_model')
    def test_issue_preview_does_not_guess_weighted_average_or_create_a_document(self, model):
        self.payload.update(kind='issue', kindEvidence='Chiqim')
        model.return_value = self.payload
        before = self.counts()
        response = self.client.post(self.endpoint, {'kind': 'issue', 'text': 'Chiqim ' + self.text}, format='json')
        self.assertEqual(response.json()['kind'], 'issue')
        self.assertTrue(all(row['unitCost'] is None for row in response.json()['rows']))
        self.assertEqual(before, self.counts())

    @patch('apps.inventory.ai_documents._read_model')
    def test_standard_units_convert_deterministically_without_purchase_unit_guessing(self, model):
        self.potato.purchase_unit = 'qop'
        self.potato.purchase_factor = Decimal('50000')
        self.potato.save()
        model.return_value = self.payload
        response = self.client.post(self.endpoint, {'text': self.text}, format='json')
        row = response.json()['rows'][0]
        self.assertEqual(row['quantity'], '2000')
        self.assertEqual(row['inputUnit'], 'base')
        self.assertEqual(row['unitCost'], '15')
        self.assertEqual(Decimal(row['quantity']) * Decimal(row['unitCost']), Decimal('30000'))

    @patch('apps.inventory.ai_documents._read_model')
    def test_kg_and_litre_conversion_preserves_total_value_in_normal_document_lines(self, model):
        from apps.inventory.services import create_document

        self.potato.purchase_unit = 'qop'
        self.potato.purchase_factor = Decimal('50000')
        self.potato.save()
        oil = InventoryItem.objects.create(restaurant=self.restaurant, name='Yog‘', base_unit='ml', purchase_unit='kanistr', purchase_factor=5000)
        text = 'Kirim: Kartoshka 2 kg, narx 10000 so‘m/kg; Yog‘ 3 l, narx 20000 so‘m/l.'
        self.payload['rows'] = [self.row('Kartoshka', self.potato, '2', 'kg', '10000', 'Kartoshka 2 kg, narx 10000 so‘m/kg', 'narx 10000 so‘m/kg'),
                                self.row('Yog‘', oil, '3', 'l', '20000', 'Yog‘ 3 l, narx 20000 so‘m/l', 'narx 20000 so‘m/l')]
        model.return_value = self.payload
        before = self.counts()
        response = self.client.post(self.endpoint, {'text': text}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(before, self.counts())
        rows = response.json()['rows']
        self.assertEqual([(row['quantity'], row['inputUnit'], row['unitCost']) for row in rows], [('2000', 'base', '10'), ('3000', 'base', '20')])
        # Explicit fixture confirmation goes through the ordinary draft service;
        # preview itself has already been asserted to perform no writes.
        draft = create_document(self.restaurant, {'kind': 'receipt', 'warehouse': str(self.warehouse.pk), 'lines': [
            {'item': row['item'], 'quantity': row['quantity'], 'input_unit': row['inputUnit'], 'unit_cost': row['unitCost']} for row in rows
        ]}, actor=self.user)
        self.assertEqual(sum((line.base_quantity * line.base_unit_cost for line in draft.lines.all()), Decimal('0')), Decimal('80000'))

    @patch('apps.inventory.ai_documents._read_model')
    def test_text_and_file_inputs_are_bounded_before_provider_call(self, model):
        for body in ({}, {'text': 'x' * 40001}, {'text': self.text, 'kind': 'transfer'}, {'text': self.text, 'post': True}, {'text': self.text, 'warehouse': 'bad-id'}):
            response = self.client.post(self.endpoint, body, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        model.assert_not_called()

    @patch('apps.inventory.ai_documents._read_model')
    def test_utf8_file_normalization_is_read_only(self, model):
        model.return_value = self.payload
        before = self.counts()
        response = self.client.post(self.endpoint, {'files': [SimpleUploadedFile('receipt.txt', self.text.encode('utf-8'), content_type='text/plain')]}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['rows'][0]['quantity'], '2')
        self.assertEqual(before, self.counts())

    @patch('apps.inventory.ai_documents._read_model')
    def test_image_rows_require_an_actual_image_and_explicit_review(self, model):
        self.payload['rows'][0]['source'] = 'image'
        model.return_value = self.payload
        first = self.client.post(self.endpoint, {'text': self.text}, format='json')
        self.assertIsNone(first.json()['rows'][0]['quantity'])
        image = io.BytesIO()
        Image.new('RGB', (10, 10), 'white').save(image, format='PNG')
        second = self.client.post(self.endpoint, {'files': [SimpleUploadedFile('receipt.png', image.getvalue(), content_type='image/png')]}, format='multipart')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.json()['needsReview'])
        self.assertTrue(second.json()['rows'][0]['warnings'])

    @override_settings(INVENTORY_AI_API_KEY='not-a-real-key', INVENTORY_AI_MODEL='configured-model')
    @patch('apps.inventory.ai_documents.httpx.Client')
    def test_provider_uses_strict_schema_without_tools_storage_or_foreign_catalog_data(self, client_type):
        response = MagicMock()
        response.json.return_value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(self.payload)}]}]}
        client = client_type.return_value.__enter__.return_value
        client.post.return_value = response
        before = self.counts()
        result = preview_inventory_document(self.restaurant, [{'type': 'input_text', 'text': self.text}])
        body = client.post.call_args.kwargs['json']
        self.assertFalse(body['store'])
        self.assertTrue(body['text']['format']['strict'])
        self.assertNotIn('tools', body)
        serialized = json.dumps(body)
        self.assertNotIn(str(self.foreign_item.pk), serialized)
        self.assertNotIn('not-a-real-key', serialized)
        self.assertEqual(result['rows'][0]['quantity'], '2')
        self.assertEqual(before, self.counts())

    @override_settings(INVENTORY_AI_API_KEY='private-key', INVENTORY_AI_MODEL='configured-model')
    @patch('apps.inventory.ai_documents.httpx.Client')
    def test_provider_failure_is_inline_safe_and_never_mutates(self, client_type):
        client_type.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError('private-key must not leak')
        before = self.counts()
        response = self.client.post(self.endpoint, {'text': self.text}, format='json')
        self.assertEqual(response.status_code, 503, response.data)
        self.assertNotIn('private-key', str(response.data))
        self.assertEqual(before, self.counts())

    @override_settings(INVENTORY_AI_API_KEY='not-a-real-key', INVENTORY_AI_MODEL='configured-model')
    @patch('apps.inventory.ai_documents.httpx.Client')
    def test_invalid_structured_response_fails_closed(self, client_type):
        invalid = copy.deepcopy(self.payload)
        invalid['rows'][0]['post'] = True
        response = MagicMock()
        response.json.return_value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(invalid)}]}]}
        client_type.return_value.__enter__.return_value.post.return_value = response
        with self.assertRaises(InventoryDocumentAIUnavailable):
            _read_model([{'type': 'input_text', 'text': self.text}], [self.potato], 'auto', 'uz')
