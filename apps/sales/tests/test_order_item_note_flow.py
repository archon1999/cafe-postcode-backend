from rest_framework import status

from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase


class OrderItemNoteFlowApiTests(PosAPITestCase):
    def create_takeaway_order(self, *, order_note=''):
        return self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': order_note,
            }
        )['id']

    def test_order_and_item_notes_are_stored_independently(self):
        order_id = self.create_takeaway_order(order_note='Butun buyurtma tezroq')

        first_item = self.add_item_via_api(order_id, note='  Piyozsiz  ')
        second_item = self.add_item_via_api(order_id)

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.note, 'Butun buyurtma tezroq')
        self.assertEqual(OrderItem.objects.get(pk=first_item['id']).note, 'Piyozsiz')
        self.assertEqual(OrderItem.objects.get(pk=second_item['id']).note, '')

    def test_item_note_can_be_updated_before_kitchen_dispatch(self):
        order_id = self.create_takeaway_order()
        item = self.add_item_via_api(order_id)

        response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item['id']}/",
            {'note': '  Kamroq tuz  '},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['note'], 'Kamroq tuz')
        self.assertEqual(OrderItem.objects.get(pk=item['id']).note, 'Kamroq tuz')

    def test_item_note_rejects_more_than_500_characters(self):
        order_id = self.create_takeaway_order()

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {
                'catalog_item': str(self.catalog_item.id),
                'quantity': 1,
                'note': 'x' * 501,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('note', response.data)

    def test_bulk_items_keep_separate_notes_and_print_as_separate_lines(self):
        order_id = self.create_takeaway_order(order_note='Umumiy izoh')

        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/bulk/',
            {
                'items': [
                    {
                        'catalog_item': str(self.catalog_item.id),
                        'quantity': 2,
                        'note': 'Ko‘proq pishloq',
                    },
                    {
                        'catalog_item': str(self.catalog_item.id),
                        'quantity': 1,
                        'note': 'Piyozsiz',
                    },
                ]
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            list(OrderItem.objects.filter(order_id=order_id).values_list('quantity', 'note')),
            [(2, 'Ko‘proq pishloq'), (1, 'Piyozsiz')],
        )

        self.submit_order_via_api(order_id)
        order_item = OrderItem.objects.filter(order_id=order_id).first()
        snapshot = order_item.kitchen_ticket_line.ticket.print_document.data_snapshot
        self.assertEqual(
            [(item['quantity'], item['note']) for item in snapshot['items']],
            [(2, 'Ko‘proq pishloq'), (1, 'Piyozsiz')],
        )

    def test_dispatched_item_note_remains_immutable_and_print_snapshot_keeps_it(self):
        order_id = self.create_takeaway_order(order_note='Umumiy izoh')
        item = self.add_item_via_api(order_id, note='Piyozsiz')

        submitted_order = self.submit_order_via_api(order_id)
        response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item['id']}/",
            {'note': 'Boshqa izoh'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('note', response.data)
        self.assertEqual(OrderItem.objects.get(pk=item['id']).note, 'Piyozsiz')
        self.assertEqual(submitted_order['note'], 'Umumiy izoh')
        self.assertEqual(submitted_order['items'][0]['note'], 'Piyozsiz')

        order_item = OrderItem.objects.select_related('kitchen_ticket_line__ticket__print_document').get(pk=item['id'])
        snapshot = order_item.kitchen_ticket_line.ticket.print_document.data_snapshot
        self.assertEqual(snapshot['order']['note'], 'Umumiy izoh')
        self.assertEqual(snapshot['items'][0]['note'], 'Piyozsiz')
