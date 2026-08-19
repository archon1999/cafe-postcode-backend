from django.test import TestCase

from apps.catalog.models import CatalogItem
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.sales.serializers import OrderItemSerializer


class ServiceManualPriceSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Manual price restaurant')
        cls.order = Order.objects.create(
            restaurant=cls.restaurant,
            channel=Order.Channel.TAKEAWAY,
        )
        cls.service = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            name='Yetkazib berish',
            item_type=CatalogItem.ItemType.SERVICE,
            price=0,
        )
        cls.product = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            name='Lavash',
            item_type=CatalogItem.ItemType.PRODUCT,
            price=32000,
        )

    def test_service_requires_manual_price(self):
        serializer = OrderItemSerializer(
            data={'catalog_item': str(self.service.id), 'quantity': 1}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('manual_price', serializer.errors)

    def test_service_snapshots_entered_price(self):
        serializer = OrderItemSerializer(
            data={
                'catalog_item': str(self.service.id),
                'quantity': 1,
                'manual_price': 75000,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        order_item = serializer.save(order=self.order)
        self.assertEqual(order_item.base_unit_price, 75000)
        self.assertEqual(order_item.unit_price, 75000)
        self.assertEqual(order_item.line_total, 75000)

    def test_product_rejects_manual_price_override(self):
        serializer = OrderItemSerializer(
            data={
                'catalog_item': str(self.product.id),
                'quantity': 1,
                'manual_price': 1,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('manual_price', serializer.errors)

    def test_manual_price_cannot_change_after_item_is_added(self):
        create_serializer = OrderItemSerializer(
            data={
                'catalog_item': str(self.service.id),
                'quantity': 1,
                'manual_price': 75000,
            }
        )
        self.assertTrue(create_serializer.is_valid(), create_serializer.errors)
        order_item = create_serializer.save(order=self.order)

        update_serializer = OrderItemSerializer(
            order_item,
            data={'manual_price': 90000},
            partial=True,
        )

        self.assertFalse(update_serializer.is_valid())
        self.assertIn('manual_price', update_serializer.errors)
