from rest_framework import status

from apps.kitchen.models import KitchenTicket, TvMonitorDevice
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class TvMonitorPairingApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=None)

    def create_pairing(self):
        response = self.client.post('/api/v1/pos/monitor/tv-pairings/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.json()

    def claim_pairing(self, pairing):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/v1/pos/monitor/tv-pairings/{pairing['id']}/claim/",
            {'claim_token': pairing['claimToken']},
            format='json',
        )
        self.client.force_authenticate(user=None)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response

    def pairing_status(self, pairing):
        return self.client.get(
            f"/api/v1/pos/monitor/tv-pairings/{pairing['id']}/",
            HTTP_X_TV_PAIRING_TOKEN=pairing['pollToken'],
        )

    def test_qr_pairing_links_tv_to_restaurant_and_serves_monitor_queue(self):
        self.restaurant.pos_monitor_variant = self.restaurant.PosMonitorVariant.LIGHT_COMPACT
        self.restaurant.save(update_fields=['pos_monitor_variant', 'updated_at'])
        pairing = self.create_pairing()

        pending_response = self.pairing_status(pairing)

        self.assertEqual(pending_response.status_code, status.HTTP_200_OK)
        self.assertEqual(pending_response.json()['status'], 'pending')

        self.claim_pairing(pairing)
        paired_response = self.pairing_status(pairing)

        self.assertEqual(paired_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paired_response.json()['status'], 'paired')
        self.assertEqual(paired_response.json()['restaurantContext']['restaurantId'], str(self.restaurant.id))
        self.assertEqual(paired_response.json()['restaurantContext']['posMonitorVariant'], 'light_compact')
        self.assertNotIn('authCode', paired_response.json()['restaurantContext'])

        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=501,
            display_name='51',
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.SUBMITTED,
        )
        KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.NEW,
        )

        queue_response = self.client.get(
            '/api/v1/pos/monitor/tv-kitchen-queue/',
            HTTP_X_TV_TOKEN=pairing['pollToken'],
        )

        self.assertEqual(queue_response.status_code, status.HTTP_200_OK, queue_response.data)
        self.assertEqual(queue_response.json()['monitorVariant'], 'light_compact')
        self.assertEqual(queue_response.json()['preparing'][0]['displayName'], '51')
        device = TvMonitorDevice.objects.get(restaurant=self.restaurant)
        self.assertIsNone(device.revoked_at)

    def test_restaurant_code_rotation_requires_pairing_again(self):
        pairing = self.create_pairing()
        self.claim_pairing(pairing)
        initial_response = self.client.get(
            '/api/v1/pos/monitor/tv-kitchen-queue/',
            HTTP_X_TV_TOKEN=pairing['pollToken'],
        )
        self.assertEqual(initial_response.status_code, status.HTTP_200_OK)

        self.restaurant.auth_code = 'ROTATE'
        self.restaurant.save(update_fields=['auth_code', 'updated_at'])
        rotated_response = self.client.get(
            '/api/v1/pos/monitor/tv-kitchen-queue/',
            HTTP_X_TV_TOKEN=pairing['pollToken'],
        )

        self.assertEqual(rotated_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(rotated_response.json()['code'], 'tv_pairing_required')
        self.assertIsNotNone(TvMonitorDevice.objects.get(restaurant=self.restaurant).revoked_at)

    def test_paired_tv_can_send_client_diagnostics(self):
        pairing = self.create_pairing()
        self.claim_pairing(pairing)

        with self.assertLogs('apps.kitchen.tv_monitor_diagnostics', level='INFO') as captured_logs:
            response = self.client.post(
                '/api/v1/pos/monitor/tv-diagnostics/',
                {
                    'event': 'queue_success',
                    'message': 'Queue rendered',
                    'context': {'preparing_count': 2, 'ready_count': 1},
                },
                format='json',
                HTTP_X_TV_TOKEN=pairing['pollToken'],
                HTTP_USER_AGENT='TV test client',
            )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIn('queue_success', captured_logs.output[0])
        self.assertIn(str(self.restaurant.id), captured_logs.output[0])

    def test_tv_diagnostics_rejects_an_unknown_device(self):
        response = self.client.post(
            '/api/v1/pos/monitor/tv-diagnostics/',
            {'event': 'page_loaded'},
            format='json',
            HTTP_X_TV_TOKEN='unknown-device-token',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['code'], 'tv_pairing_required')

    def test_claim_requires_authenticated_employee(self):
        pairing = self.create_pairing()

        response = self.client.post(
            f"/api/v1/pos/monitor/tv-pairings/{pairing['id']}/claim/",
            {'claim_token': pairing['claimToken']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.pairing_status(pairing).json()['status'], 'pending')
        self.assertFalse(TvMonitorDevice.objects.exists())
