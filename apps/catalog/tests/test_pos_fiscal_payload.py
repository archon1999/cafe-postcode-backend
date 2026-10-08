import copy
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.test import TestCase as DatabaseTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.catalog.models import CatalogCategory, CatalogItem, CatalogItemGroup, CatalogItemGroupMember
from apps.catalog.serializers.pos_catalog_item import PosCatalogItemSerializer
from apps.catalog.utils.fiscal_classification import fiscal_package_code, fiscal_units
from apps.catalog.utils.pos_fiscal_payload import pos_fiscal_payload
from apps.catalog.views.pos_menu import PosMenuView
from apps.integrations.services.fiscal_drive_receipt_payload import FiscalDriveReceiptPayloadMixin
from apps.integrations.services.unikassa_receipt_payload import UnikassaReceiptPayloadMixin
from apps.local_agents.sync import _menu_snapshot
from apps.restaurants.models import Restaurant
from apps.users.models import User


class PosFiscalPayloadTests(TestCase):
    def test_shared_category_is_projected_once_and_output_dicts_are_independent(self):
        raw = {'packages': [{'code': 1378885}], 'commonUnitCode': 112, 'barcode': '00123'}
        cache = {}
        with patch('apps.catalog.utils.pos_fiscal_payload.fiscal_package_code', wraps=fiscal_package_code) as extract:
            outputs = [pos_fiscal_payload(None, raw, cache=cache) for _ in range(50)]
        self.assertEqual(extract.call_count, 2)  # None and the shared category.
        self.assertEqual(outputs[0], pos_fiscal_payload(None, raw))
        outputs[0]['primaryPackage']['code'] = 'changed'
        self.assertEqual(outputs[1]['primaryPackage']['code'], '1378885')

    def test_a_new_request_recomputes_changed_classification(self):
        raw = {'packages': [{'code': '001234'}]}
        first = pos_fiscal_payload({}, raw, cache={})
        raw['packages'][0]['code'] = '009999'
        second = pos_fiscal_payload({}, raw, cache={})
        self.assertEqual(first['primaryPackage']['code'], '001234')
        self.assertEqual(second['primaryPackage']['code'], '009999')

    def test_large_raw_tasnif_becomes_bounded_classification_without_mutation(self):
        source = {'commonUnitCode': 112, 'barcode': '001234', 'createdBy': 'unused',
                  'packages': [{'code': 1000 + i, 'name': 'x' * 1000, 'isUnitPackage': '1' if i == 4 else '2'}
                               for i in range(417)]}
        original = copy.deepcopy(source)
        payload = pos_fiscal_payload({}, source)
        self.assertEqual(payload, {'primaryPackage': {'code': '1004'}, 'unitCode': 112, 'barcode': '001234'})
        self.assertEqual(source, original)
        self.assertLess(len(json.dumps(payload)), 150)
        self.assertEqual(fiscal_package_code(payload), fiscal_package_code(source))
        self.assertEqual(fiscal_units(payload), fiscal_units(source))

    def test_item_precedence_and_category_fallback_match_receipt_providers(self):
        cases = [
            ({'unitCode': None}, {'commonUnitCode': 112, 'packages': [{'code': '001234'}], 'gtin': '00123456789012'}),
            ({'unitCode': 796, 'packageCode': '0007', 'nested': {'barcode': '00-123'}}, {'unitCode': 112, 'barcode': '999'}),
            ({}, {'primaryPackage': {'code': '0007'}, 'unitCode': 796}),
            ({'barcode': ''}, {'barcode': '00123'}),
            ({}, {}),
        ]
        for item_payload, category_payload in cases:
            with self.subTest(item=item_payload, category=category_payload):
                item = SimpleNamespace(catalog_item=SimpleNamespace(mxik_payload=item_payload,
                                        category=SimpleNamespace(mxik_payload=category_payload)))
                projected = pos_fiscal_payload(item_payload, category_payload)
                self.assertNotIn('packageCode', projected)
                for provider in (FiscalDriveReceiptPayloadMixin, UnikassaReceiptPayloadMixin):
                    service = provider()
                    service.settings = {}
                    self.assertEqual(fiscal_package_code(projected), service._extract_package_code(item=item))
                    self.assertEqual(fiscal_units(projected) or 796, service._extract_units(item=item))
                self.assertEqual(projected.get('barcode', ''), FiscalDriveReceiptPayloadMixin()._extract_barcode(item=item))

    def test_serializer_keeps_saved_classification_unchanged(self):
        item = SimpleNamespace(mxik_payload={'unitCode': None, 'barcode': '001234'},
                               category=SimpleNamespace(mxik_payload={'commonUnitCode': 112, 'packages': [{'code': 1378885}]}))
        self.assertEqual(PosCatalogItemSerializer().get_mxik_payload(item),
                         {'primaryPackage': {'code': '1378885'}, 'unitCode': 112, 'barcode': '001234'})
        self.assertEqual(item.mxik_payload, {'unitCode': None, 'barcode': '001234'})


class CompactMenuSnapshotTests(DatabaseTestCase):
    def test_reverse_menu_prefetch_shares_the_parent_category(self):
        from django.db.models import Prefetch
        restaurant = Restaurant.objects.create(name='Shared menu graph')
        category = CatalogCategory.objects.create(restaurant=restaurant, name='Category', mxik_payload={'packages': [{'code': 1378885}]})
        for index in range(3):
            CatalogItem.objects.create(restaurant=restaurant, category=category, name=f'Item {index}', price=1000)
        items = CatalogItem.objects.filter(is_active=True, is_stoplisted=False).select_related('prep_station')
        loaded = CatalogCategory.objects.prefetch_related(Prefetch('items', queryset=items, to_attr='active_menu_items')).get(pk=category.pk)
        with self.assertNumQueries(0):
            self.assertTrue(all(item.category is loaded for item in loaded.active_menu_items))

    def test_online_and_offline_menu_keep_products_translations_groups_and_restrictions(self):
        restaurant = Restaurant.objects.create(name='Compact menu fixture')
        user = User.objects.create_superuser(username='compact-menu-admin', password='test-secret', restaurant=restaurant)
        raw = {'commonUnitCode': 112, 'cashSale': 0, 'packages':
               [{'code': 1000 + i, 'isUnitPackage': '1' if i == 4 else '2', 'name': 'x' * 1000} for i in range(417)]}
        category = CatalogCategory.objects.create(restaurant=restaurant, name='Category', mxik_payload=raw)
        for index in range(20):
            CatalogItem.objects.create(restaurant=restaurant, category=category, name_uz=f'Taom {index}',
                                       name_ru=f'Food {index}', price=1000 + index, requires_marking=True,
                                       marking_gtin='00123456789012')
        first_item = category.items.first()
        group = CatalogItemGroup.objects.create(restaurant=restaurant, category=category, name='Group')
        CatalogItemGroupMember.objects.create(group=group, catalog_item=first_item)
        snapshot = _menu_snapshot(restaurant)
        self.assertLess(len(json.dumps(snapshot).encode()), 100000)
        self.assertEqual(len(snapshot[0]['items']), 20)
        for product in snapshot[0]['items']:
            self.assertTrue(product['requires_marking'])
            self.assertEqual(product['marking_gtin'], '00123456789012')
            self.assertTrue(product['cash_payment_forbidden'])
            self.assertIn('name_ru', product)
            self.assertEqual(product['mxik_payload'], {'primaryPackage': {'code': '1004'}, 'unitCode': 112})
        member = snapshot[0]['item_groups'][0]['members'][0]['item']
        self.assertEqual(member['mxik_payload'], snapshot[0]['items'][0]['mxik_payload'])
        # Exercise the online view with its actual queryset and permission scope.
        from django.urls import resolve
        request = APIRequestFactory().get('/api/v1/pos/catalog/menu/')
        request.resolver_match = resolve(request.path)
        force_authenticate(request, user=user)
        response = PosMenuView.as_view()(request)
        self.assertEqual(response.status_code, 200, response.data)
        online = response.data.get('data') if isinstance(response.data, dict) else response.data
        self.assertEqual(len(online[0]['items']), 20)
        self.assertEqual(online[0]['items'][0]['mxik_payload'], member['mxik_payload'])
        category.refresh_from_db()
        self.assertEqual(category.mxik_payload, raw)
