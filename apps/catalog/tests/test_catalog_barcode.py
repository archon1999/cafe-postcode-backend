from django.test import SimpleTestCase, TestCase

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.restaurants.models import Restaurant


class CatalogBarcodeTests(SimpleTestCase):
    def test_optional_barcode_and_leading_zeroes(self):
        for barcode in ('', '00123456', '001234567890', '0012345678901', '00123456789012'):
            with self.subTest(barcode=barcode):
                serializer = CatalogItemSerializer(data={'name': 'Product', 'barcode': barcode})
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data['barcode'], barcode)
                self.assertFalse(serializer.validated_data['requires_marking'])

    def test_invalid_barcode_is_rejected(self):
        for barcode in ('123', '123456789', '12345678901', '123456789012345', 'abcdefgh', '1234567\n'):
            with self.subTest(barcode=barcode):
                serializer = CatalogItemSerializer(data={'name': 'Product', 'barcode': barcode})
                self.assertFalse(serializer.is_valid())
                self.assertIn('barcode', serializer.errors)

    def test_partial_update_can_preserve_or_clear_barcode(self):
        item = CatalogItem(name='Product', barcode='00123456')
        preserve = CatalogItemSerializer(item, data={'name': 'Renamed'}, partial=True)
        self.assertTrue(preserve.is_valid(), preserve.errors)
        self.assertNotIn('barcode', preserve.validated_data)
        clear = CatalogItemSerializer(item, data={'barcode': ''}, partial=True)
        self.assertTrue(clear.is_valid(), clear.errors)
        self.assertEqual(clear.validated_data['barcode'], '')


class CatalogBarcodePersistenceTests(TestCase):
    def test_create_read_update_and_clear_preserve_barcode_as_text(self):
        restaurant = Restaurant.objects.create(name='Barcode test')
        create = CatalogItemSerializer(data={'name': 'Product', 'barcode': '0012345678901'})
        self.assertTrue(create.is_valid(), create.errors)
        item = create.save(restaurant=restaurant)
        item.refresh_from_db()
        self.assertEqual(CatalogItemSerializer(item).data['barcode'], '0012345678901')
        for barcode in ('00123456', ''):
            update = CatalogItemSerializer(item, data={'barcode': barcode}, partial=True)
            self.assertTrue(update.is_valid(), update.errors)
            update.save()
            item.refresh_from_db()
            self.assertEqual(CatalogItemSerializer(item).data['barcode'], barcode)
