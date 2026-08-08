from types import SimpleNamespace

from apps.catalog.models import CatalogItemModifierGroup, ModifierGroup, ModifierOption
from apps.catalog.serializers import CatalogItemSerializer
from apps.sales.models import Order, OrderItem, OrderItemModifier
from apps.sales.tests.support.pos_api import PosAPITestCase


class OrderItemModifierApiTests(PosAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dough_group = ModifierGroup.objects.create(
            restaurant=cls.restaurant,
            name='Xamir turi',
            selection_type=ModifierGroup.SelectionType.SINGLE,
            min_selections=1,
            max_selections=1,
        )
        cls.thin_option = ModifierOption.objects.create(group=cls.dough_group, name='Yupqa', price_delta=0)
        cls.cheese_option = ModifierOption.objects.create(
            group=cls.dough_group,
            name='Pishloqli bort',
            price_delta=27000,
            sort_order=1,
        )
        CatalogItemModifierGroup.objects.create(catalog_item=cls.catalog_item, modifier_group=cls.dough_group)

    def create_takeaway_order(self):
        return self.create_order_via_api({'channel': Order.Channel.TAKEAWAY, 'guest_count': 1, 'note': ''})['id']

    def test_catalog_item_serializer_accepts_modifier_group_ids_for_current_restaurant(self):
        request = SimpleNamespace(
            user=self.user,
            path=f'/api/v1/admin/catalog/items/{self.catalog_item.id}/',
            headers={},
        )
        serializer = CatalogItemSerializer(
            self.catalog_item,
            data={'modifier_groups': [str(self.dough_group.id)]},
            partial=True,
            context={'request': request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(list(self.catalog_item.modifier_groups.values_list('id', flat=True)), [self.dough_group.id])

    def test_pos_menu_exposes_modifier_groups_and_prices(self):
        response = self.client.get('/api/v1/pos/catalog/menu/')

        self.assertEqual(response.status_code, 200, response.data)
        categories = response.data.get('data', response.data) if isinstance(response.data, dict) else response.data
        menu_item = next(item for category in categories for item in category['items'] if item['id'] == str(self.catalog_item.id))
        self.assertEqual(menu_item['modifier_groups'][0]['name'], 'Xamir turi')
        self.assertEqual(menu_item['modifier_groups'][0]['min_selections'], 1)
        self.assertEqual(
            [(option['name'], option['price_delta']) for option in menu_item['modifier_groups'][0]['options']],
            [('Yupqa', 0), ('Pishloqli bort', 27000)],
        )

    def test_paid_modifier_is_server_priced_and_snapshotted(self):
        order_id = self.create_takeaway_order()
        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {
                'catalog_item': str(self.catalog_item.id),
                'quantity': 2,
                'selected_modifiers': [
                    {'group': str(self.dough_group.id), 'options': [str(self.cheese_option.id)]},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['base_unit_price'], 30000)
        self.assertEqual(response.data['unit_price'], 57000)
        self.assertEqual(response.data['line_total'], 114000)
        self.assertEqual(response.data['modifiers'][0]['option_name'], 'Pishloqli bort')
        self.assertEqual(response.data['modifiers'][0]['group_id'], str(self.dough_group.id))
        self.assertEqual(response.data['modifiers'][0]['option_id'], str(self.cheese_option.id))
        order_item = OrderItem.objects.get(pk=response.data['id'])
        snapshot = OrderItemModifier.objects.get(order_item=order_item)
        self.assertEqual((snapshot.group_name, snapshot.option_name, snapshot.price_delta), ('Xamir turi', 'Pishloqli bort', 27000))
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.subtotal, 114000)
        self.assertEqual(order.total, 125400)

        self.cheese_option.name = 'Yangi nom'
        self.cheese_option.price_delta = 99000
        self.cheese_option.save()
        snapshot.refresh_from_db()
        order_item.refresh_from_db()
        self.assertEqual((snapshot.option_name, snapshot.price_delta), ('Pishloqli bort', 27000))
        self.assertEqual(order_item.unit_price, 57000)

    def test_bulk_endpoint_adds_several_configurations_in_one_request(self):
        order_id = self.create_takeaway_order()
        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/bulk/',
            {
                'items': [
                    {
                        'catalog_item': str(self.catalog_item.id),
                        'quantity': 3,
                        'selected_modifiers': [
                            {'group': str(self.dough_group.id), 'options': [str(self.thin_option.id)]},
                        ],
                    },
                    {
                        'catalog_item': str(self.catalog_item.id),
                        'quantity': 2,
                        'selected_modifiers': [
                            {'group': str(self.dough_group.id), 'options': [str(self.cheese_option.id)]},
                        ],
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([item['quantity'] for item in response.data['items']], [3, 2])
        self.assertEqual([item['unit_price'] for item in response.data['items']], [30000, 57000])
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.subtotal, 204000)

    def test_required_group_is_rejected_when_missing(self):
        order_id = self.create_takeaway_order()
        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {'catalog_item': str(self.catalog_item.id), 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('selected_modifiers', response.data)

    def test_option_from_unassigned_group_is_rejected(self):
        other_group = ModifierGroup.objects.create(
            restaurant=self.restaurant,
            name='Sous',
            selection_type=ModifierGroup.SelectionType.MULTIPLE,
            min_selections=0,
            max_selections=2,
        )
        other_option = ModifierOption.objects.create(group=other_group, name='BBQ', price_delta=5000)
        order_id = self.create_takeaway_order()

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {
                'catalog_item': str(self.catalog_item.id),
                'quantity': 1,
                'selected_modifiers': [
                    {'group': str(other_group.id), 'options': [str(other_option.id)]},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('selected_modifiers', response.data)
