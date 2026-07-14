from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.users.models import AuthSession, User
from common.api.throttling import LoginRateThrottle


class AuthSessionSecurityTests(APITestCase):
    TEST_CLIENT_IP = '192.0.2.20'

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='session-security-admin',
            password='Strong-Session-Test-123!',
            full_name='Session Security Admin',
        )

    def setUp(self):
        super().setUp()
        throttle = LoginRateThrottle()
        request = APIRequestFactory().post('/', REMOTE_ADDR=self.TEST_CLIENT_IP)
        cache.delete(throttle.get_cache_key(request, None))

    def login(self):
        response = self.client.post(
            '/api/v1/admin/auth/login/',
            {'username': self.user.username, 'password': 'Strong-Session-Test-123!'},
            format='json',
            REMOTE_ADDR=self.TEST_CLIENT_IP,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data['token']

    def test_admin_token_cannot_be_used_on_pos_surface(self):
        token = self.login()

        response = self.client.get('/api/v1/pos/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_session_is_valid_for_one_day_by_default(self):
        self.login()
        session = AuthSession.objects.get(user=self.user)

        self.assertAlmostEqual(
            (session.expires_at - session.created_at).total_seconds(),
            24 * 60 * 60,
            delta=2,
        )

    def test_expired_session_is_rejected(self):
        token = self.login()
        AuthSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_new_login_keeps_previous_session_active(self):
        old_token = self.login()
        new_token = self.login()

        old_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {old_token}')
        new_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {new_token}')

        self.assertNotEqual(old_token, new_token)
        self.assertEqual(old_response.status_code, status.HTTP_200_OK)
        self.assertEqual(new_response.status_code, status.HTTP_200_OK)
        self.assertEqual(AuthSession.objects.filter(user=self.user, status=AuthSession.Status.ACTIVE).count(), 2)

    def test_logout_revokes_only_the_current_session(self):
        old_token = self.login()
        new_token = self.login()

        logout_response = self.client.post('/api/v1/admin/auth/logout/', HTTP_AUTHORIZATION=f'Token {old_token}')
        old_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {old_token}')
        new_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {new_token}')

        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(old_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(new_response.status_code, status.HTTP_200_OK)

    def test_login_throttle_contract_remains_ip_scoped_at_ten_per_minute(self):
        throttle = LoginRateThrottle()
        request = APIRequestFactory().post('/', REMOTE_ADDR='198.51.100.25')

        self.assertEqual(throttle.rate, '10/min')
        self.assertEqual(throttle.get_cache_key(request, None), 'throttle_login_198.51.100.25')

    def test_password_change_revokes_existing_session(self):
        token = self.login()
        self.user.set_password('Another-Strong-Password-456!')
        self.user.save(update_fields=['password'])

        response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
