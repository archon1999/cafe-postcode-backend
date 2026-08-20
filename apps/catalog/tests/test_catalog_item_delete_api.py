from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.restaurants.models import Restaurant
from apps.sales.models import Order, OrderItem
from apps.users.models import User


class CatalogItemDeleteApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Delete test restaurant')
        cls.superuser = User.objects.create_superuser(
            username='catalog-delete-superuser',
            password='secret123',
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Main menu',
        )

    def setUp(self):
        self.client.force_authenticate(self.superuser)

    def delete(self, item):
        return self.client.delete(
            f'/api/v1/admin/catalog/items/{item.id}/',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

    def test_unused_item_is_physically_deleted(self):
        item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Unused item',
        )

        response = self.delete(item)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.data)
        self.assertFalse(CatalogItem.objects.filter(pk=item.id).exists())

    def test_item_used_in_order_is_archived_without_destroying_history(self):
        item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Historical item',
            is_active=True,
        )
        order = Order.objects.create(restaurant=self.restaurant)
        order_item = OrderItem.objects.create(order=order, catalog_item=item, unit_price=10_000)

        response = self.delete(item)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.data)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertTrue(item.is_stoplisted)
        self.assertIsNotNone(item.archived_at)
        self.assertTrue(OrderItem.objects.filter(pk=order_item.id, catalog_item=item).exists())

        list_response = self.client.get(
            '/api/v1/admin/catalog/items/',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )
        detail_response = self.client.get(
            f'/api/v1/admin/catalog/items/{item.id}/',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.data)
        self.assertNotIn(str(item.id), {row['id'] for row in list_response.data['data']})
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
