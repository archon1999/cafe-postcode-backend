from rest_framework import status

from apps.users.models import Permission
from apps.floor.models import TableSession
from apps.sales.models import Order
from apps.platform.models import RestaurantEntitlement, Tariff
from apps.sales.tests.support.pos_api import PosAPITestCase


class TariffCapabilityApiTests(PosAPITestCase):
    def test_missing_cashier_permissions_block_open_checks_and_payments(self):
        self.tariff.permissions.remove(
            Permission.objects.get(code='pos_open_checks.view'),
            Permission.objects.get(code='pos_payments.create'),
        )
        order_data = self.create_order_via_api(
            {
                'distribution_point': str(self.takeaway_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            }
        )
        self.add_item_via_api(order_data['id'])

        open_checks_response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')
        payment_response = self.client.post(
            f"/api/v1/pos/billing/orders/{order_data['id']}/pay/",
            {'method': 'cash', 'amount': 30000},
            format='json',
        )

        self.assertEqual(open_checks_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(payment_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_kitchen_permission_blocks_queue(self):
        self.tariff.permissions.remove(Permission.objects.get(code='pos_kitchen_orders.view'))

        response = self.client.get('/api/v1/pos/kitchen/queue/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_hall_permission_blocks_hall_list(self):
        self.tariff.permissions.remove(Permission.objects.get(code='pos_halls.view'))

        response = self.client.get('/api/v1/pos/floor/halls/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tariff_capability_does_not_leak_between_restaurants(self):
        second_restaurant = self.restaurant.__class__.objects.create(name='Second restaurant')
        second_tariff = Tariff.objects.create(
            name='Second restaurant restricted tariff',
            description='Restricted hall access',
            monthly_price=0,
            yearly_price=0,
            is_active=True,
        )
        second_tariff.permissions.set(Permission.objects.filter(code__in={'pos_kitchen_orders.view', 'pos_payments.create'}))
        second_tariff.allowed_roles.set([self.role])
        second_entitlement = RestaurantEntitlement.objects.create(
            restaurant=second_restaurant,
            tariff=second_tariff,
            is_active=True,
            is_custom=False,
        )
        second_user = self.user.__class__.objects.create_user(
            username='second-pos-user',
            password='secret123',
            full_name='Second POS User',
            restaurant=second_restaurant,
            role=self.role,
        )

        self.client.force_authenticate(self.user)
        first_response = self.client.get('/api/v1/pos/floor/halls/')

        self.client.force_authenticate(second_user)
        second_response = self.client.get('/api/v1/pos/floor/halls/')

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn('pos_halls.view', second_entitlement.get_effective_permission_codes())

