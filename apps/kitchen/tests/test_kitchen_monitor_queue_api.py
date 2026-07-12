from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from apps.kitchen.models import KitchenTicket
from apps.restaurants.models import DistributionPoint, PrepStation, Restaurant
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class KitchenMonitorQueueApiTests(PosAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_restaurant = Restaurant.objects.create(name='Other restaurant', service_fee_percent=5)
        cls.other_distribution = DistributionPoint.objects.create(
            restaurant=cls.other_restaurant,
            name='Other takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )
        cls.other_prep_station = PrepStation.objects.create(
            restaurant=cls.other_restaurant,
            name='Other kitchen',
            kind=cls.prep_station.kind,
        )

    def create_ticket(
        self,
        *,
        restaurant,
        distribution_point,
        order_number,
        status,
        completed_at=None,
    ):
        order = Order.objects.create(
            restaurant=restaurant,
            distribution_point=distribution_point,
            opened_by=self.user,
            order_number=order_number,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.READY if status == KitchenTicket.Status.DONE else Order.Status.SUBMITTED,
            guest_count=1,
        )
        return KitchenTicket.objects.create(
            restaurant=restaurant,
            order=order,
            prep_station=self.prep_station if restaurant == self.restaurant else self.other_prep_station,
            status=status,
            routed_via=KitchenTicket.RouteMode.DISPLAY,
            completed_at=completed_at,
        )

    def test_monitor_queue_is_authenticated_and_returns_minimal_payload(self):
        self.create_ticket(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            order_number=101,
            status=KitchenTicket.Status.NEW,
        )
        self.create_ticket(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            order_number=102,
            status=KitchenTicket.Status.COOKING,
        )
        self.create_ticket(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            order_number=103,
            status=KitchenTicket.Status.DONE,
            completed_at=timezone.now() - timedelta(seconds=30),
        )
        self.create_ticket(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            order_number=104,
            status=KitchenTicket.Status.DONE,
            completed_at=timezone.now() - timedelta(minutes=3),
        )
        self.create_ticket(
            restaurant=self.other_restaurant,
            distribution_point=self.other_distribution,
            order_number=201,
            status=KitchenTicket.Status.NEW,
        )

        response = self.client.get(f'/api/v1/pos/monitor/kitchen-queue/?restaurant_id={self.restaurant.id}')
        payload = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['orderNumber'] for item in payload['preparing']], [101, 102])
        self.assertEqual([item['orderNumber'] for item in payload['recentlyDone']], [103])
        self.assertEqual(set(payload['preparing'][0].keys()), {'id', 'orderNumber', 'status', 'completedAt'})
        self.assertEqual(set(payload['recentlyDone'][0].keys()), {'id', 'orderNumber', 'status', 'completedAt'})

    def test_monitor_queue_requires_valid_restaurant_id(self):
        missing_response = self.client.get('/api/v1/pos/monitor/kitchen-queue/')
        invalid_response = self.client.get('/api/v1/pos/monitor/kitchen-queue/?restaurant_id=00000000-0000-0000-0000-000000000000')

        self.assertEqual(missing_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_monitor_queue_rejects_anonymous_request(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(f'/api/v1/pos/monitor/kitchen-queue/?restaurant_id={self.restaurant.id}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_monitor_queue_rejects_another_restaurant(self):
        response = self.client.get(
            f'/api/v1/pos/monitor/kitchen-queue/?restaurant_id={self.other_restaurant.id}'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
