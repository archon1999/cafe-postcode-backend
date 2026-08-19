from unittest.mock import Mock, patch

from rest_framework import status
from rest_framework.test import APITestCase

from apps.integrations.api.admin.views import MartaConnectionCheckView
from apps.restaurants.models import Restaurant
from apps.users.models import User


class MartaConnectionCheckApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='MARTA Test Restaurant')
        cls.superuser = User.objects.create_superuser(
            username='marta-test-superuser', password='secret123', full_name='MARTA Test Superuser'
        )

    def setUp(self):
        self.client.force_authenticate(self.superuser)
        self.client.credentials(HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id))

    def test_blank_endpoint_uses_auto_discovery(self):
        service = Mock()
        service.execute.return_value = {
            'ok': True,
            'devices': [{'endpointUrl': 'http://192.168.1.25:8090', 'status': 'READY'}],
        }

        with patch.object(MartaConnectionCheckView, 'command_service_class', return_value=service):
            response = self.client.post('/api/v1/admin/integrations/marta/check/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['ok'])
        self.assertEqual(response.data['endpointUrl'], 'http://192.168.1.25:8090')
        service.execute.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='marta.discover',
            payload={'port': 8090, 'timeoutMillis': 900, 'maxConcurrency': 96},
            timeout_seconds=35,
        )

    def test_explicit_address_checks_health_and_adds_default_port(self):
        service = Mock()
        service.local_http_request.return_value = {
            'ok': True,
            'body': {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
        }

        with patch.object(MartaConnectionCheckView, 'command_service_class', return_value=service):
            response = self.client.post(
                '/api/v1/admin/integrations/marta/check/',
                {'endpointUrl': '192.168.1.30'},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['ok'])
        self.assertEqual(response.data['endpointUrl'], 'http://192.168.1.30:8090')
        service.local_http_request.assert_called_once_with(
            restaurant=self.restaurant,
            method='GET',
            url='http://192.168.1.30:8090/health',
            purpose='marta',
            timeout_seconds=10,
        )

    def test_explicit_address_rejects_credentials_query_fragment_and_non_http_scheme(self):
        for endpoint in (
            'http://user:password@192.168.1.30:8090',
            'http://192.168.1.30:8090?token=secret',
            'http://192.168.1.30:8090#secret',
            'https://192.168.1.30:8090',
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(
                    '/api/v1/admin/integrations/marta/check/',
                    {'endpointUrl': endpoint},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['code'], 'MARTA_ADDRESS_INVALID')
                self.assertNotIn('secret', str(response.data))
                self.assertNotIn('password', str(response.data))
