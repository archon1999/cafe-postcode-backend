from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogCategory, CatalogItem, CatalogItemGroup
from apps.restaurants.models import Restaurant
from apps.users.models import User


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CatalogItemGroupApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Grouped menu restaurant')
        cls.other_restaurant = Restaurant.objects.create(name='Other restaurant')
        cls.user = User.objects.create_superuser(
            username='group-admin',
            password='secret123',
            restaurant=cls.restaurant,
        )
        cls.category = CatalogCategory.objects.create(restaurant=cls.restaurant, name='Pitsa')
        cls.items = [
            CatalogItem.objects.create(
                restaurant=cls.restaurant,
                category=cls.category,
                name=f'Pepperoni {size}',
                price=price,
                sort_order=index,
            )
            for index, (size, price) in enumerate((('S', 40_000), ('M', 55_000), ('L', 70_000)))
        ]

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_admin_can_group_products_and_pos_menu_keeps_variants(self):
        response = self.client.post(
            '/api/v1/admin/catalog/item-groups/',
            {
                'category': str(self.category.id),
                'name': 'Pepperoni',
                'description': 'Uch razmer',
                'is_active': True,
                'members': [
                    {'catalog_item': str(item.id), 'variant_name': size, 'sort_order': index}
                    for index, (item, size) in enumerate(zip(self.items, ('S', 'M', 'L'), strict=True))
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual([member['variant_name'] for member in response.data['members']], ['S', 'M', 'L'])
        self.assertEqual(CatalogItemGroup.objects.get().members.count(), 3)

        menu_response = self.client.get('/api/v1/pos/catalog/menu/')

        self.assertEqual(menu_response.status_code, status.HTTP_200_OK, menu_response.data)
        menu_payload = menu_response.data.get('data', menu_response.data)
        category = next(row for row in menu_payload if row['id'] == str(self.category.id))
        self.assertEqual(len(category['items']), 3)
        self.assertEqual(category['item_groups'][0]['name'], 'Pepperoni')
        self.assertEqual(
            [member['item']['name'] for member in category['item_groups'][0]['members']],
            ['Pepperoni S', 'Pepperoni M', 'Pepperoni L'],
        )

    def test_group_rejects_products_from_different_categories(self):
        other_category = CatalogCategory.objects.create(restaurant=self.restaurant, name='Burger')
        other_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=other_category,
            name='Burger S',
            price=30_000,
        )

        response = self.client.post(
            '/api/v1/admin/catalog/item-groups/',
            {
                'category': str(self.category.id),
                'name': 'Invalid',
                'members': [
                    {'catalog_item': str(self.items[0].id), 'variant_name': 'S'},
                    {'catalog_item': str(other_item.id), 'variant_name': 'M'},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('members', response.data)

    def test_superuser_can_manage_groups_from_all_branches_scope(self):
        self.client.credentials()

        create_response = self.client.post(
            '/api/v1/admin/catalog/item-groups/',
            {
                'category': str(self.category.id),
                'name': 'All branches Pepperoni',
                'members': [
                    {'catalog_item': str(item.id), 'variant_name': size, 'sort_order': index}
                    for index, (item, size) in enumerate(zip(self.items[:2], ('S', 'M'), strict=True))
                ],
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        group_id = create_response.data['id']
        self.assertEqual(CatalogItemGroup.objects.get(pk=group_id).restaurant_id, self.restaurant.id)

        list_response = self.client.get(
            '/api/v1/admin/catalog/item-groups/',
            {'category': str(self.category.id)},
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.data)
        self.assertEqual([group['id'] for group in list_response.data], [group_id])
