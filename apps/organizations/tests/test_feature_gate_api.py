from rest_framework import status

from apps.floor.models import TableSession
from apps.orders.models import Order
from common.tests.pos_api import PosAPITestCase


class FeatureGateApiTests(PosAPITestCase):
    def test_cashier_disabled_blocks_open_checks_and_payments(self):
        self.feature_config.cashier_enabled = False
        self.feature_config.save(update_fields=['cashier_enabled', 'updated_at'])
        order_data = self.create_order_via_api(
            {
                'distribution_point': str(self.takeaway_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        self.add_item_via_api(order_data['id'])

        open_checks_response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')
        payment_response = self.client.post(
            f"/api/v1/pos/payments/orders/{order_data['id']}/pay/",
            {'method': 'cash', 'amount': 30000},
            format='json',
        )

        self.assertEqual(open_checks_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(payment_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_kitchen_disabled_blocks_queue(self):
        self.feature_config.kitchen_enabled = False
        self.feature_config.save(update_fields=['kitchen_enabled', 'updated_at'])

        response = self.client.get('/api/v1/pos/kitchen/queue/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hall_disabled_blocks_hall_list(self):
        self.feature_config.hall_enabled = False
        self.feature_config.save(update_fields=['hall_enabled', 'updated_at'])

        response = self.client.get('/api/v1/pos/halls/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_feature_gate_does_not_leak_between_restaurants(self):
        second_restaurant = self.restaurant.__class__.objects.create(name='Second restaurant')
        second_branch = self.branch.__class__.objects.create(
            restaurant=second_restaurant,
            name='Second branch',
            service_fee_percent=10,
            is_default=True,
        )
        second_feature_config = self.feature_config.__class__.objects.create(
            restaurant=second_restaurant,
            hall_enabled=False,
            kitchen_enabled=False,
            cashier_enabled=False,
            owner_dashboard_enabled=True,
        )
        second_user = self.user.__class__.objects.create_user(
            username='second-pos-user',
            password='secret123',
            full_name='Second POS User',
            restaurant=second_restaurant,
            branch=second_branch,
            role=self.role,
            ui_mode=self.user.ui_mode,
        )

        self.client.force_authenticate(self.user)
        first_response = self.client.get('/api/v1/pos/halls/')

        self.client.force_authenticate(second_user)
        second_response = self.client.get('/api/v1/pos/halls/')

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(second_feature_config.hall_enabled)
