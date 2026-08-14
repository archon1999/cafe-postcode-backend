from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from apps.local_agents.models import LocalAgent
from apps.users.models import EmployeeProfile, User
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

    def test_pos_restaurant_code_returns_background_image_url(self):
        self.restaurant.pos_auth_background_image = 'restaurants/auth-backgrounds/test/login.png'
        self.restaurant.save(update_fields=['pos_auth_background_image'])
        storage = self.restaurant.pos_auth_background_image.storage

        with patch.object(storage, 'url', return_value='https://cdn.example.com/login.png'):
            response = self.client.post(
                '/api/v1/pos/auth/restaurant-code/',
                {'code': self.restaurant.auth_code},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['restaurant_id'], str(self.restaurant.id))
        self.assertEqual(response.data['restaurant_name'], self.restaurant.name)
        self.assertEqual(response.data['pos_auth_background_image_url'], 'https://cdn.example.com/login.png')
        self.assertTrue(response.data['service_fee_enabled'])
        self.assertEqual(response.data['service_fee_percent'], '10.00')

    def test_pos_restaurant_code_returns_null_background_image_url_without_image(self):
        response = self.client.post(
            '/api/v1/pos/auth/restaurant-code/',
            {'code': self.restaurant.auth_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['pos_auth_background_image_url'])

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_pos_restaurant_code_returns_matching_coordinator_credentials(self, execute):
        LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')
        LocalAgent.objects.filter(restaurant=self.restaurant).update(lan_endpoints=['http://192.168.1.20:18181'])
        execute.return_value = {
            'restaurantId': str(self.restaurant.id),
            'edgeToken': 'ept_terminal-secret',
            'coordinatorUrls': ['http://192.168.1.20:18181'],
        }

        response = self.client.post(
            '/api/v1/pos/auth/restaurant-code/',
            {
                'code': self.restaurant.auth_code,
                'terminal_id': 'pos-terminal-12345678',
                'terminal_name': 'Main POS',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['coordinator']['restaurantId'], str(self.restaurant.id))
        self.assertEqual(response.data['coordinator']['edgeToken'], 'ept_terminal-secret')
        self.assertEqual(response.data['coordinator']['coordinatorUrls'], ['http://192.168.1.20:18181'])
        execute.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='edge.terminal.issue',
            payload={'terminalId': 'pos-terminal-12345678', 'terminalName': 'Main POS'},
            timeout_seconds=2,
        )

    @patch('apps.users.api.pos.views.auth.LocalAgentCommandService.execute')
    def test_pos_restaurant_code_filters_invalid_coordinator_urls(self, execute):
        LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')
        LocalAgent.objects.filter(restaurant=self.restaurant).update(
            lan_endpoints=[None, '', 'not-a-url', 'http://192.168.1.20:18181', 'http://127.0.0.1:18181']
        )
        execute.return_value = {'edgeToken': 'ept_terminal-secret'}

        response = self.client.post(
            '/api/v1/pos/auth/restaurant-code/',
            {'code': self.restaurant.auth_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
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

