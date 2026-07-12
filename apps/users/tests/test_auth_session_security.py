from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import AuthSession, User


class AuthSessionSecurityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='session-security-admin',
            password='Strong-Session-Test-123!',
            full_name='Session Security Admin',
        )

    def login(self):
        response = self.client.post(
            '/api/v1/admin/auth/login/',
            {'username': self.user.username, 'password': 'Strong-Session-Test-123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data['token']

    def test_admin_token_cannot_be_used_on_pos_surface(self):
        token = self.login()

        response = self.client.get('/api/v1/pos/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_session_is_rejected(self):
        token = self.login()
        AuthSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_new_login_rotates_previous_token(self):
        old_token = self.login()
        new_token = self.login()

        old_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {old_token}')
        new_response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {new_token}')

        self.assertNotEqual(old_token, new_token)
        self.assertEqual(old_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(new_response.status_code, status.HTTP_200_OK)

    def test_password_change_revokes_existing_session(self):
        token = self.login()
        self.user.set_password('Another-Strong-Password-456!')
        self.user.save(update_fields=['password'])

        response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
