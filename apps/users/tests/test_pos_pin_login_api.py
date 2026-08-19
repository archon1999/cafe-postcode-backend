from unittest.mock import patch
from datetime import timedelta

from rest_framework import status
from rest_framework.test import APITestCase
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.local_agents.models import LocalAgent
from apps.devices.models import Device
from apps.users.models import AuthSession, EmployeeProfile, User
from apps.sales.tests.support.pos_api import PosTestDataMixin


class PosPinLoginApiTests(PosTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.set_pin('1111')
        cls.user.save(update_fields=['pin_code'])

        cls.inactive_user = User.objects.create_user(
            username='inactive-pos-user',
            password='secret123',
            full_name='Inactive POS User',
            restaurant=cls.restaurant,
            role=cls.role,
            is_active=False,
        )
        cls.inactive_user.set_pin('2222')
        cls.inactive_user.save(update_fields=['pin_code'])
        cls.inactive_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.INACTIVE
        cls.inactive_user.employee_profile.save(update_fields=['employment_status'])

        cls.archived_user = User.objects.create_user(
            username='archived-pos-user',
            password='secret123',
            full_name='Archived POS User',
            restaurant=cls.restaurant,
            role=cls.role,
            is_active=False,
        )
        cls.archived_user.set_pin('3333')
        cls.archived_user.save(update_fields=['pin_code'])
        cls.archived_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.ARCHIVED
        cls.archived_user.employee_profile.save(update_fields=['employment_status'])

    def _paired_transport_session(self):
        now = timezone.now()
        agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')
        agent_device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.LOCAL_AGENT,
            name='Site coordinator',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key='A' * 43,
            public_key_fingerprint='a' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(days=1),
        )
        agent.device = agent_device
        agent.lan_endpoints = ['http://192.168.1.20:18181']
        agent.save(update_fields=['device', 'lan_endpoints', 'updated_at'])
        pos_device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Main POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='B' * 122,
            public_key_fingerprint='b' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(days=1),
        )
        session = AuthSession.objects.create(
            user=self.user,
            device=pos_device,
            restaurant=self.restaurant,
            token_key_hash=AuthSession.build_token_key_hash('transport-session'),
            surface=AuthSession.Surface.POS,
            expires_at=now + timedelta(hours=1),
            last_seen_at=now,
        )
        self.client.force_authenticate(user=self.user, token=session)
        return agent, agent_device, pos_device

    def test_pos_pin_login_accepts_four_digit_pin_for_active_employee(self):
        self.restaurant.pos_auth_background_image = 'restaurants/auth-backgrounds/test/login.png'
        self.restaurant.save(update_fields=['pos_auth_background_image'])
        storage = self.restaurant.pos_auth_background_image.storage

        with patch.object(storage, 'url', return_value='https://cdn.example.com/login.png'):
            response = self.client.post(
                '/api/v1/pos/auth/pin-login/',
                {'restaurant_id': str(self.restaurant.id), 'pin': '1111'},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], self.user.username)
        self.assertTrue(response.data['restaurant_access_active'])
        self.assertIn(self.role.code, response.data['role_codes'])
        self.assertEqual(response.data['tariff']['id'], str(self.tariff.id))
        self.assertIn('pos_halls.view', response.data['user']['permission_codes'])
        self.assertEqual(
            response.data['restaurant_context']['pos_auth_background_image_url'],
            'https://cdn.example.com/login.png',
        )
        self.assertTrue(response.data['restaurant_context']['service_fee_enabled'])
        self.assertEqual(response.data['restaurant_context']['service_fee_percent'], '10.00')
        self.assertTrue(response.data['restaurant_context']['vat_enabled'])
        self.assertEqual(response.data['restaurant_context']['vat_percent'], '12.00')

    def test_restaurant_code_endpoint_is_fail_closed_outside_migration_window(self):
        response = self.client.post(
            '/api/v1/pos/auth/restaurant-code/',
            {'code': 'LEGACY'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)

    def test_pre_cutover_restaurant_code_returns_context_but_no_auth_credential(self):
        now = timezone.now()
        type(self.restaurant).objects.filter(pk=self.restaurant.pk).update(created_at=now - timedelta(hours=1))
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE restaurants_restaurant SET auth_code = %s WHERE id = %s',
                ['ABC123', str(self.restaurant.id).replace('-', '')],
            )
        with override_settings(
            DEVICE_LEGACY_POS_MIGRATION_ENABLED=True,
            DEVICE_LEGACY_MIGRATION_STARTED_AT=(now - timedelta(seconds=1)).isoformat(),
            DEVICE_LEGACY_MIGRATION_DEADLINE=(now + timedelta(hours=1)).isoformat(),
        ):
            response = self.client.post(
                '/api/v1/pos/auth/restaurant-code/',
                {'code': 'ABC123'},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['restaurant_id'], str(self.restaurant.id))
        self.assertNotIn('token', response.data)
        self.assertNotIn('edge_token', response.data)

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_device_bound_session_prebinds_public_key_without_returning_a_token(self, execute):
        _agent, agent_device, pos_device = self._paired_transport_session()
        execute.return_value = {
            'terminalId': 'pos-terminal-12345678',
            'deviceId': str(pos_device.id),
            'restaurantId': str(self.restaurant.id),
            'coordinatorUrls': ['http://192.168.1.20:18181'],
        }

        response = self.client.post(
            '/api/v1/pos/auth/transport/',
            {
                'terminal_id': 'pos-terminal-12345678',
                'terminal_name': 'Main POS',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['coordinator']['restaurantId'], str(self.restaurant.id))
        self.assertNotIn('edgeToken', response.data['coordinator'])
        self.assertEqual(response.data['coordinator']['coordinatorUrls'], ['http://192.168.1.20:18181'])
        self.assertEqual(response.data['coordinator']['agentDeviceId'], str(agent_device.id))
        self.assertEqual(response.data['coordinator']['agentSigningPublicKey'], agent_device.public_key)
        execute.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='edge.terminal.bind',
            payload={
                'terminalId': 'pos-terminal-12345678',
                'terminalName': 'Main POS',
                'deviceId': str(pos_device.id),
                'publicKeyAlgorithm': 'P256_SHA256',
                'publicKey': pos_device.public_key,
                'publicKeyFingerprint': pos_device.public_key_fingerprint,
            },
            timeout_seconds=2,
        )

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_transport_discovery_filters_invalid_coordinator_urls(self, execute):
        agent, _agent_device, _pos_device = self._paired_transport_session()
        agent.lan_endpoints = [None, '', 'not-a-url', 'http://192.168.1.20:18181', 'http://127.0.0.1:18181']
        agent.save(update_fields=['lan_endpoints', 'updated_at'])
        execute.return_value = {
            'terminalId': str(_pos_device.id),
            'deviceId': str(_pos_device.id),
            'restaurantId': str(self.restaurant.id),
        }

        response = self.client.post('/api/v1/pos/auth/transport/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['coordinator']['coordinatorUrls'], ['http://192.168.1.20:18181'])
        self.assertNotIn('edgeToken', response.data['coordinator'])

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_transport_discovery_rejects_expired_agent_device_lease(self, execute):
        _agent, agent_device, _pos_device = self._paired_transport_session()
        agent_device.lease_expires_at = timezone.now() - timedelta(seconds=1)
        agent_device.save(update_fields=['lease_expires_at', 'updated_at'])

        response = self.client.post('/api/v1/pos/auth/transport/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['coordinator'])
        execute.assert_not_called()

    def test_legacy_session_discovery_never_reissues_or_returns_edge_token(self):
        agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')
        agent.lan_endpoints = ['http://192.168.1.20:18181']
        agent.save(update_fields=['lan_endpoints', 'updated_at'])
        self.client.force_authenticate(user=self.user)

        response = self.client.post('/api/v1/pos/auth/transport/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('edgeToken', response.data['coordinator'])
        self.assertEqual(response.data['coordinator']['coordinatorUrls'], ['http://192.168.1.20:18181'])

    def test_pos_pin_login_rejects_inactive_employee_with_explicit_message(self):
        response = self.client.post(
            '/api/v1/pos/auth/pin-login/',
            {'restaurant_id': str(self.restaurant.id), 'pin': '2222'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('inactive', response.data['pin'][0].lower())

    def test_pos_pin_login_rejects_archived_employee_with_explicit_message(self):
        response = self.client.post(
            '/api/v1/pos/auth/pin-login/',
            {'restaurant_id': str(self.restaurant.id), 'pin': '3333'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('archived', response.data['pin'][0].lower())

    def test_pos_pin_login_requires_exactly_four_digits(self):
        response = self.client.post(
            '/api/v1/pos/auth/pin-login/',
            {'restaurant_id': str(self.restaurant.id), 'pin': '11111'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pin', response.data)
        self.assertIn('4', str(response.data['pin'][0]))

