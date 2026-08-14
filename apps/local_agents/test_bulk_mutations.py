from rest_framework import status

from apps.local_agents.models import LocalAgent
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class LocalAgentBulkMutationTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        _agent, self.token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name='Site coordinator',
        )

    def test_weighted_order_items_are_allowed_through_agent_replay(self):
        self.catalog_item.sale_unit = 'kg'
        self.catalog_item.save(update_fields=['sale_unit', 'updated_at'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=9091,
            channel=Order.Channel.TAKEAWAY,
        )
        operation = {
            'operationId': 'edge-weighted-bulk-item-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/sales/orders/{order.id}/items/bulk/',
            'body': {
                'items': [
                    {
                        'catalogItem': str(self.catalog_item.id),
                        'quantity': 1.4,
                        'note': '',
                    }
                ]
            },
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertEqual(result['status'], status.HTTP_201_CREATED)
        item = order.items.get()
        self.assertEqual(item.sale_unit, 'kg')
        self.assertEqual(float(item.quantity), 1.4)
