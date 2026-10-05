from types import SimpleNamespace
from unittest import TestCase

from apps.catalog.utils.fiscal_classification import fiscal_package_code, fiscal_units
from apps.catalog.serializers.pos_catalog_item import PosCatalogItemSerializer
from apps.integrations.services.fiscal_drive_receipt_payload import FiscalDriveReceiptPayloadMixin
from apps.integrations.services.unikassa_receipt_payload import UnikassaReceiptPayloadMixin


class FiscalClassificationTests(TestCase):
    def test_tasnif_primary_package_selection(self):
        cases = [
            ({'packages': [{'code': 1860960, 'parentCode': 1378885, 'isUnitPackage': '2'},
                           {'code': 1378885, 'parentCode': None, 'isUnitPackage': '1'}]}, '1378885'),
            ({'packages': [{'code': 1860960, 'parentCode': 1378885},
                           {'code': '1378885', 'parentCode': None}]}, '1378885'),
            ({'packages': [{'code': '1860960', 'parentCode': 1378885}]}, '1860960'),
            ({'packageCode': '001234', 'packages': [{'code': 1378885}]}, '001234'),
            ({'packageCode': None, 'packages': [{'code': 1378885}]}, '1378885'),
            ({'primaryPackage': {'code': '001234'}}, '001234'),
            ({'package': {'code': '001234'}}, '001234'),
            ({'mxikCode': '02202002006000000', 'packages': [None, {'code': ''}]}, ''),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(fiscal_package_code(payload), expected)

    def test_units_are_separate_from_package_and_skip_empty_aliases(self):
        self.assertEqual(fiscal_units({'unitCode': None, 'commonUnitCode': 112}), 112)
        self.assertEqual(fiscal_units({'unitCode': 0}, {'unitCode': 112}), 112)
        self.assertIsNone(fiscal_units({'packageCode': 1378885, 'packages': [{'code': 1378885}]}))

    def test_both_providers_use_item_then_category_classification(self):
        for mixin in (FiscalDriveReceiptPayloadMixin, UnikassaReceiptPayloadMixin):
            service = mixin()
            service.settings = {}
            category = SimpleNamespace(mxik_payload={'commonUnitCode': 112, 'packages': [{'code': 1378885}]})
            item = SimpleNamespace(catalog_item=SimpleNamespace(mxik_payload={'unitCode': None}, category=category))
            with self.subTest(provider=mixin.__name__):
                self.assertEqual(service._extract_units(item=item), 112)
                self.assertEqual(service._extract_package_code(item=item), '1378885')
                item.catalog_item.mxik_payload = {'unitCode': 796, 'packageCode': '001234'}
                self.assertEqual(service._extract_units(item=item), 796)
                self.assertEqual(service._extract_package_code(item=item), '001234')

    def test_pos_snapshot_keeps_category_fallback_for_partial_item_payload(self):
        category = SimpleNamespace(mxik_payload={'commonUnitCode': 112, 'packages': [{'code': 1378885}]})
        catalog_item = SimpleNamespace(mxik_payload={'unitCode': None, 'barcode': '001234'}, category=category)
        payload = PosCatalogItemSerializer.get_mxik_payload(catalog_item)
        self.assertEqual(payload['packageCode'], '1378885')
        self.assertEqual(payload['unitCode'], 112)
        self.assertEqual(payload['barcode'], '001234')
        self.assertEqual(catalog_item.mxik_payload, {'unitCode': None, 'barcode': '001234'})
