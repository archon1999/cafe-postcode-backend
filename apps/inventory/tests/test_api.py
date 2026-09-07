from decimal import Decimal
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User
from apps.inventory.models import InventoryAttachment, InventoryItem, StockBalance, StockDocument, StockMovement, Supplier
from apps.inventory import services


class InventoryAPITests(TestCase):
    base = '/api/v1/admin/inventory/'

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Ombor API')
        self.other = Restaurant.objects.create(name='Other tenant')
        self.warehouse = services.default_warehouse(self.restaurant)
        self.other_warehouse = services.default_warehouse(self.other)
        self.item = InventoryItem.objects.create(restaurant=self.restaurant, name='Kartoshka', base_unit='g', purchase_factor=1000)
        self.supplier = Supplier.objects.create(restaurant=self.restaurant, name='Ta’minotchi')
        self.catalog = CatalogItem.objects.create(restaurant=self.restaurant, name='Qovurma')
        role = Role.objects.create(code='inventory-test-admin', name='Ombor admin')
        codes = ['admin.inventory.view', 'admin.inventory.manage', 'admin.inventory.post', 'admin.inventory.view_cost']
        role.permissions.set(Permission.objects.filter(code__in=codes))
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.restaurant, is_active=True, is_custom=True)
        entitlement.permissions.set(role.permissions.all())
        self.user = User.objects.create_user('inventory-api', restaurant=self.restaurant, role=role, full_name='Omborchi')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_document(self, **kwargs):
        data = {'kind': 'receipt', 'warehouse': str(self.warehouse.pk), 'supplier': str(self.supplier.pk),
                'reference': 'KIR-1', 'responsibleName': 'Omborchi',
                'lines': [{'item': str(self.item.pk), 'quantity': '1000', 'unitCost': '8'}], **kwargs}
        response = self.client.post(self.base + 'documents/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.json()

    def test_full_receipt_recipe_count_reports_and_exports_flow(self):
        doc = self.create_document(idempotencyKey='api-flow')
        self.assertEqual(doc['status'], 'draft')
        posted = self.client.post(self.base + f'documents/{doc["id"]}/post/', {}, format='json')
        self.assertEqual(posted.status_code, 200, posted.data)
        self.assertEqual(Decimal(posted.json()['totalValue']), Decimal('8000'))
        recipe = self.client.post(self.base + 'recipes/', {'catalogItem': str(self.catalog.pk),
                            'lines': [{'item': str(self.item.pk), 'quantity': '100'}]}, format='json')
        self.assertEqual(recipe.status_code, 201, recipe.data)
        self.assertEqual(Decimal(recipe.json()['estimatedCost']), Decimal('800'))
        count = self.create_document(kind='stocktake', reason='Smena sanashi', lines=[{'item': str(self.item.pk), 'quantity': None}])
        self.assertIsNone(count['lines'][0]['quantity'])
        self.assertFalse(count['lines'][0]['countRecorded'])
        self.assertEqual(self.client.post(self.base + f'documents/{count["id"]}/post/', {}, format='json').status_code, 400)
        edited = self.client.patch(self.base + f'documents/{count["id"]}/', {'lines': [{'item': str(self.item.pk), 'quantity': '980'}]}, format='json')
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(self.client.post(self.base + f'documents/{count["id"]}/post/', {}, format='json').status_code, 200)
        balance = self.client.get(self.base + 'balances/').json()[0]
        self.assertEqual(Decimal(balance['quantity']), Decimal('980'))
        self.assertEqual(Decimal(self.client.get(self.base + 'variance/').json()[0]['varianceValue']), Decimal('-160'))
        for report in ['balances', 'movements', 'variance']:
            response = self.client.get(self.base + 'export/', {'report': report})
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(self.client.get(self.base + f'documents/{doc["id"]}/export/').status_code, 200)

    def test_posted_document_and_lines_are_immutable(self):
        doc = self.create_document()
        endpoint = self.base + f'documents/{doc["id"]}/'
        self.client.post(endpoint + 'post/', {}, format='json')
        response = self.client.patch(endpoint, {'reference': 'Changed'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn(self.client.delete(endpoint).status_code, (403, 405))
        self.assertTrue(StockDocument.objects.filter(pk=doc['id']).exists())
        reversed_doc = self.client.post(endpoint + 'reverse/', {'reason': 'Xato'}, format='json')
        self.assertEqual(reversed_doc.status_code, 200, reversed_doc.data)
        self.assertEqual(reversed_doc.json()['reversalOf'], doc['id'])
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_stale_stocktake_error_follows_accept_language_and_preserves_snapshot(self):
        receipt = self.create_document()
        self.client.post(self.base + f'documents/{receipt["id"]}/post/', {}, format='json')
        count = self.create_document(kind='stocktake', reason='Smena sanashi',
                    lines=[{'item': str(self.item.pk), 'quantity': '980'}])
        subsequent = self.create_document()
        self.client.post(self.base + f'documents/{subsequent["id"]}/post/', {}, format='json')
        expected = {
            None: 'Kartoshka: sanash davomida harakat bo‘lgan. Yangi inventarizatsiya yarating.',
            'uz': 'Kartoshka: sanash davomida harakat bo‘lgan. Yangi inventarizatsiya yarating.',
            'ru': 'Kartoshka: во время пересчёта были движения по складу. Создайте новую инвентаризацию.',
            'uz-crl': 'Kartoshka: санаш давомида ҳаракат бўлган. Янги инвентаризация яратинг.',
        }
        for language, message in expected.items():
            with self.subTest(language=language):
                headers = {'HTTP_ACCEPT_LANGUAGE': language} if language else {}
                response = self.client.post(self.base + f'documents/{count["id"]}/post/',
                                            {}, format='json', **headers)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.json(), {'lines': message})
                self.assertEqual(response.data['lines'].code, 'invalid')
        document = StockDocument.objects.get(pk=count['id'])
        self.assertEqual(document.status, 'draft')
        self.assertEqual(document.lines.get().expected_quantity, Decimal('1000'))
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(StockBalance.objects.get(warehouse=self.warehouse, item=self.item).quantity, Decimal('2000'))

    def test_insufficient_stock_error_follows_accept_language_without_posting(self):
        receipt = self.create_document()
        self.client.post(self.base + f'documents/{receipt["id"]}/post/', {}, format='json')
        issue = self.create_document(kind='issue', reason='Oshxona uchun',
                    lines=[{'item': str(self.item.pk), 'quantity': '1001'}])
        expected = {
            None: 'Kartoshka: omborda yetarli qoldiq yo‘q.',
            'ru': 'Kartoshka: недостаточный остаток на складе.',
            'uz-crl': 'Kartoshka: омборда етарли қолдиқ йўқ.',
        }
        for language, message in expected.items():
            with self.subTest(language=language):
                headers = {'HTTP_ACCEPT_LANGUAGE': language} if language else {}
                response = self.client.post(self.base + f'documents/{issue["id"]}/post/',
                                            {}, format='json', **headers)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.json(), {'lines': message})
                self.assertEqual(response.data['lines'].code, 'invalid')
        self.assertEqual(StockDocument.objects.get(pk=issue['id']).status, 'draft')
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(warehouse=self.warehouse, item=self.item).quantity, Decimal('1000'))

    def test_scope_isolation_for_every_read_and_write(self):
        foreign_item = InventoryItem.objects.create(restaurant=self.other, name='Hidden secret', base_unit='g')
        self.assertEqual(self.client.get(self.base + f'items/{foreign_item.pk}/').status_code, 404)
        self.assertEqual(self.client.patch(self.base + f'items/{foreign_item.pk}/', {'name': 'Stolen'}, format='json').status_code, 404)
        for report in ['balances', 'movements', 'variance', 'overview', 'insights']:
            response = self.client.get(self.base + report + '/', {'warehouse': str(self.other_warehouse.pk)})
            self.assertEqual(response.status_code, 400, response.data)
        response = self.client.post(self.base + 'recipes/', {'catalogItem': str(self.catalog.pk),
                     'lines': [{'item': str(foreign_item.pk), 'quantity': '1'}]}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('Hidden secret', str(self.client.get(self.base + 'items/').data))

    def test_costs_are_redacted_and_cost_write_requires_separate_permission(self):
        doc = self.create_document()
        self.client.post(self.base + f'documents/{doc["id"]}/post/', {}, format='json')
        self.user.role.permissions.remove(Permission.objects.get(code='admin.inventory.view_cost'))
        self.assertIsNone(self.client.get(self.base + 'balances/').json()[0]['averageCost'])
        self.assertIsNone(self.client.get(self.base + 'overview/').json()['stockValue'])
        self.assertIsNone(self.client.get(self.base + f'documents/{doc["id"]}/').json()['lines'][0]['unitCost'])
        export = self.client.get(self.base + 'export/', {'report': 'balances'}).content.decode('utf-8-sig')
        self.assertNotIn('average_cost', export)
        response = self.client.post(self.base + 'documents/', {'kind': 'opening', 'warehouse': str(self.warehouse.pk),
                  'lines': [{'item': str(self.item.pk), 'quantity': '1', 'unitCost': '100'}]}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_no_cost_permission_quantity_edit_preserves_existing_cost(self):
        doc = self.create_document()
        self.user.role.permissions.remove(Permission.objects.get(code='admin.inventory.view_cost'))
        response = self.client.patch(self.base + f'documents/{doc["id"]}/',
                         {'lines': [{'item': str(self.item.pk), 'quantity': '500'}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.json()['lines'][0]['unitCost'])
        self.assertEqual(StockDocument.objects.get(pk=doc['id']).lines.get().unit_cost, Decimal('8'))

    def test_draft_stocktake_previews_counted_difference_and_keeps_unknown_values_null(self):
        receipt = self.create_document(lines=[{'item': str(self.item.pk), 'quantity': '1200', 'unitCost': '8'}])
        self.client.post(self.base + f'documents/{receipt["id"]}/post/', {}, format='json')
        count = self.create_document(kind='stocktake', reason='Smena sanashi',
                    lines=[{'item': str(self.item.pk), 'quantity': None}])
        self.assertIsNone(count['totalValue'])
        uncounted = count['lines'][0]
        for field in ('quantity', 'baseQuantity', 'varianceQuantity', 'varianceValue', 'unitCost'):
            self.assertIsNone(uncounted[field], field)
        response = self.client.patch(self.base + f'documents/{count["id"]}/',
                    {'lines': [{'item': str(self.item.pk), 'quantity': '1100'}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        preview = response.json()['lines'][0]
        self.assertEqual(Decimal(preview['expectedQuantity']), Decimal('1200'))
        self.assertEqual(Decimal(preview['baseQuantity']), Decimal('1100'))
        self.assertEqual(Decimal(preview['varianceQuantity']), Decimal('-100'))
        self.assertIsNone(preview['varianceValue'])
        self.assertIsNone(preview['unitCost'])
        # Preview is a read projection, never a stock movement before posting.
        self.assertEqual(StockBalance.objects.get(warehouse=self.warehouse, item=self.item).quantity, Decimal('1200'))
        posted = self.client.post(self.base + f'documents/{count["id"]}/post/', {}, format='json')
        self.assertEqual(posted.status_code, 200, posted.data)
        self.assertEqual(Decimal(posted.json()['lines'][0]['varianceValue']), Decimal('-800'))

    def test_view_manage_post_are_independent_permissions_and_all_need_view(self):
        doc = self.create_document()
        self.user.role.permissions.remove(Permission.objects.get(code='admin.inventory.post'))
        self.assertEqual(self.client.post(self.base + f'documents/{doc["id"]}/post/', {}, format='json').status_code, 403)
        self.user.role.permissions.remove(Permission.objects.get(code='admin.inventory.manage'))
        self.assertEqual(self.client.post(self.base + 'items/', {'name': 'No', 'baseUnit': 'g'}, format='json').status_code, 403)
        self.assertEqual(self.client.get(self.base + 'items/').status_code, 200)
        self.user.role.permissions.remove(Permission.objects.get(code='admin.inventory.view'))
        self.assertEqual(self.client.get(self.base + 'items/').status_code, 403)

    def test_catalog_options_does_not_require_catalog_permission(self):
        response = self.client.get(self.base + 'catalog-options/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['id'], str(self.catalog.pk))

    def test_base_unit_cannot_change_after_recipe_or_document(self):
        self.create_document()
        response = self.client.patch(self.base + f'items/{self.item.pk}/', {'baseUnit': 'ml'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_active_recipe_blocks_ingredient_archiving(self):
        services.create_recipe(self.restaurant, {'catalog_item': str(self.catalog.pk),
                               'lines': [{'item': str(self.item.pk), 'quantity': '1'}]}, self.user)
        response = self.client.patch(self.base + f'items/{self.item.pk}/', {'isActive': False}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_active)

    def test_private_attachment_download_scope_magic_and_size(self):
        field = InventoryAttachment._meta.get_field('file')
        original_storage = field.storage
        from django.core.files.storage import FileSystemStorage
        with TemporaryDirectory() as folder:
            field.storage = FileSystemStorage(location=folder)
            try:
                response = self.client.post(self.base + 'attachments/', {'file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.7\nfixture', content_type='application/pdf')}, format='multipart', HTTP_HOST='localhost')
                self.assertEqual(response.status_code, 201, response.data)
                attachment_id = response.json()['id']
                attachment_url = response.json()['url']
                doc = self.create_document(attachmentUrl=attachment_url)
                cost_permission = Permission.objects.get(code='admin.inventory.view_cost')
                self.user.role.permissions.remove(cost_permission)
                denied = self.client.get(self.base + f'attachments/{attachment_id}/download/')
                self.assertEqual(denied.status_code, 403)
                self.assertIsNone(self.client.get(self.base + f'documents/{doc["id"]}/').json()['attachmentUrl'])
                export = self.client.get(self.base + f'documents/{doc["id"]}/export/').content.decode('utf-8-sig')
                self.assertNotIn(attachment_url, export)
                edited = self.client.patch(self.base + f'documents/{doc["id"]}/',
                       {'attachmentUrl': '', 'notes': 'Mas’ul tekshirdi'}, format='json')
                self.assertEqual(edited.status_code, 200, edited.data)
                self.assertEqual(StockDocument.objects.get(pk=doc['id']).attachment_url, attachment_url)
                self.user.role.permissions.add(cost_permission)
                download = self.client.get(self.base + f'attachments/{attachment_id}/download/')
                self.assertEqual(download.status_code, 200)
                self.assertTrue(b''.join(download.streaming_content).startswith(b'%PDF'))
                attachment = InventoryAttachment.objects.get(pk=attachment_id)
                self.assertEqual(self.client.get('/media/' + attachment.file.name).status_code, 404)
                attachment.restaurant = self.other
                attachment.save()
                self.assertEqual(self.client.get(self.base + f'attachments/{attachment_id}/download/').status_code, 404)
                response = self.client.post(self.base + 'attachments/', {'file': SimpleUploadedFile('invoice.pdf', b'<html>script</html>')}, format='multipart')
                self.assertEqual(response.status_code, 400)
            finally:
                field.storage = original_storage

    def test_csv_prevents_formula_injection(self):
        self.item.name = '=HYPERLINK("https://invalid.example")'
        self.item.save()
        response = self.client.get(self.base + 'export/', {'report': 'balances'})
        self.assertIn("'=HYPERLINK", response.content.decode('utf-8-sig'))

    def test_invalid_filters_return_validation_error(self):
        for params in [{'warehouse': 'not-uuid'}, {'from': '2026-13-77'}, {'limit': 'invalid'}, {'from': '2026-09-10', 'to': '2026-09-01'}]:
            response = self.client.get(self.base + 'movements/', params)
            self.assertEqual(response.status_code, 400, response.data)
