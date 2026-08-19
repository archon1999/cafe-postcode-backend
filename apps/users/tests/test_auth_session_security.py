from datetime import timedelta
from time import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.devices.models import SecurityEvent
from apps.users.models import (
    AdminMFAChallenge,
    AdminMFAProfile,
    AdminRefreshFamily,
    AdminRefreshToken,
    AuthSession,
    User,
)
from apps.users.services.admin_mfa import totp_code, totp_code_digest, verify_totp
from common.api.throttling import LoginRateThrottle


TEST_ORIGIN = 'https://admin.cafe-postcode.uz'
TEST_FERNET_KEY = Fernet.generate_key().decode('ascii')


@override_settings(
    ADMIN_MFA_REQUIRED=True,
    ADMIN_AUTH_ALLOWED_ORIGINS=[TEST_ORIGIN],
    ADMIN_MFA_FERNET_KEYS=[TEST_FERNET_KEY],
    ADMIN_REFRESH_RACE_GRACE_SECONDS=5,
    ADMIN_IDLE_LOCK_SECONDS=20 * 60,
)
class AuthSessionSecurityTests(APITestCase):
    TEST_CLIENT_IP = '192.0.2.20'
    PASSWORD = 'Strong-Session-Test-123!'

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='session-security-admin',
            password=cls.PASSWORD,
            full_name='Session Security Admin',
        )

    def setUp(self):
        super().setUp()
        cache.clear()

    def _post(self, path, data=None, **extra):
        extra.setdefault('HTTP_ORIGIN', TEST_ORIGIN)
        extra.setdefault('REMOTE_ADDR', self.TEST_CLIENT_IP)
        return self.client.post(path, data or {}, format='json', **extra)

    def _begin_login(self):
        response = self._post(
            '/api/v1/admin/auth/login/',
            {'username': self.user.username, 'password': self.PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        return response.json()

    def enroll_and_login(self):
        challenge_payload = self._begin_login()
        self.assertEqual(challenge_payload['status'], 'mfa_enrollment_required')
        challenge_token = challenge_payload['challengeToken']

        start = self._post(
            '/api/v1/admin/auth/mfa/enrollment/start/',
            {'challengeToken': challenge_token},
        )
        self.assertEqual(start.status_code, status.HTTP_200_OK, start.data)
        secret = start.json()['secret']
        code = totp_code(secret, int(time()) // 30)
        confirm = self._post(
            '/api/v1/admin/auth/mfa/enrollment/confirm/',
            {'challengeToken': challenge_token, 'code': code},
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK, confirm.data)
        return confirm.json(), secret

    def _access_header(self, payload):
        return {'HTTP_AUTHORIZATION': f"Token {payload['accessToken']}"}

    def test_superuser_must_enroll_mfa_before_any_access_or_refresh_cookie(self):
        login = self._begin_login()

        self.assertNotIn('accessToken', login)
        self.assertNotIn(settings.ADMIN_REFRESH_COOKIE_NAME, self.client.cookies)
        challenge = AdminMFAChallenge.objects.get(user=self.user)
        self.assertNotEqual(challenge.token_hash, login['challengeToken'])

        payload, secret = self.enroll_and_login()
        profile = AdminMFAProfile.objects.get(user=self.user)
        family = AdminRefreshFamily.objects.get(user=self.user)
        session = AuthSession.objects.get(refresh_family=family, status=AuthSession.Status.ACTIVE)

        self.assertEqual(payload['status'], 'authenticated')
        self.assertEqual(len(payload['recoveryCodes']), 10)
        self.assertNotEqual(profile.encrypted_secret, secret)
        self.assertNotIn(secret, profile.encrypted_secret)
        self.assertEqual(len(profile.last_totp_code_digest), 64)
        self.assertNotEqual(profile.last_totp_code_digest, totp_code(secret, profile.last_totp_counter))
        self.assertEqual(len(profile.recovery_code_hashes), 10)
        self.assertTrue(all(code not in profile.recovery_code_hashes for code in payload['recoveryCodes']))
        self.assertAlmostEqual((session.expires_at - session.created_at).total_seconds(), 15 * 60, delta=2)
        self.assertAlmostEqual(
            (family.absolute_expires_at - family.created_at).total_seconds(),
            30 * 24 * 60 * 60,
            delta=2,
        )

    def test_refresh_cookie_is_strict_host_only_secure_http_only_and_hash_only(self):
        self.enroll_and_login()

        raw_refresh = self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME].value
        cookie = self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME]
        token = AdminRefreshToken.objects.get()

        self.assertEqual(settings.ADMIN_REFRESH_COOKIE_NAME, '__Host-cafe_admin_refresh')
        self.assertEqual(cookie['path'], '/')
        self.assertEqual(cookie['domain'], '')
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertTrue(cookie['expires'])
        self.assertTrue(cookie['max-age'])
        self.assertNotEqual(token.token_hash, raw_refresh)
        self.assertEqual(token.token_hash, AdminRefreshToken.build_token_hash(raw_refresh))
        self.assertFalse(any(field.name in {'token', 'raw_token', 'secret'} for field in token._meta.fields))

    def test_refresh_rotates_once_race_grace_does_not_revoke_then_reuse_revokes_family(self):
        payload, _ = self.enroll_and_login()
        old_refresh = self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME].value
        family = AdminRefreshFamily.objects.get(user=self.user)

        rotated = self._post('/api/v1/admin/auth/refresh/')
        self.assertEqual(rotated.status_code, status.HTTP_200_OK, rotated.data)
        new_refresh = self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME].value
        self.assertNotEqual(old_refresh, new_refresh)
        old_row = AdminRefreshToken.objects.get(token_hash=AdminRefreshToken.build_token_hash(old_refresh))
        self.assertIsNotNone(old_row.used_at)
        self.assertIsNotNone(old_row.replaced_by_id)
        self.assertEqual(
            AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).count(),
            1,
        )
        self.assertNotEqual(payload['accessToken'], rotated.json()['accessToken'])

        self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME] = old_refresh
        race = self._post('/api/v1/admin/auth/refresh/')
        self.assertEqual(race.status_code, status.HTTP_409_CONFLICT, race.data)
        self.assertEqual(race.json()['code'], 'refresh_race')
        family.refresh_from_db()
        self.assertEqual(family.status, AdminRefreshFamily.Status.ACTIVE)

        old_row.used_at = timezone.now() - timedelta(seconds=6)
        old_row.save(update_fields=['used_at', 'updated_at'])
        reused = self._post('/api/v1/admin/auth/refresh/')
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED, reused.data)
        self.assertEqual(reused.json()['code'], 'refresh_reuse_detected')
        family.refresh_from_db()
        self.assertEqual(family.status, AdminRefreshFamily.Status.REVOKED)
        self.assertIsNotNone(family.reuse_detected_at)
        self.assertFalse(AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).exists())
        self.assertTrue(SecurityEvent.objects.filter(event_type='ADMIN_REFRESH_REUSE_DETECTED').exists())

    def test_refresh_enforces_absolute_expiry_and_revokes_family(self):
        self.enroll_and_login()
        family = AdminRefreshFamily.objects.get(user=self.user)
        family.absolute_expires_at = timezone.now() - timedelta(seconds=1)
        family.save(update_fields=['absolute_expires_at', 'updated_at'])

        response = self._post('/api/v1/admin/auth/refresh/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.data)
        self.assertEqual(response.json()['code'], 'refresh_expired')
        family.refresh_from_db()
        self.assertEqual(family.status, AdminRefreshFamily.Status.REVOKED)

    def test_idle_refresh_locks_server_side_without_counting_refresh_as_activity(self):
        self.enroll_and_login()
        family = AdminRefreshFamily.objects.get(user=self.user)
        idle_value = timezone.now() - timedelta(minutes=21)
        family.last_activity_at = idle_value
        family.save(update_fields=['last_activity_at', 'updated_at'])

        response = self._post('/api/v1/admin/auth/refresh/')

        self.assertEqual(response.status_code, 423, response.data)
        self.assertEqual(response.json()['code'], 'session_locked')
        family.refresh_from_db()
        self.assertIsNotNone(family.locked_at)
        self.assertEqual(family.last_activity_at, idle_value)
        self.assertTrue(SecurityEvent.objects.filter(event_type='ADMIN_SESSION_LOCKED', result='idle').exists())

    def test_meaningful_activity_header_touches_idle_clock_but_background_request_does_not(self):
        payload, _ = self.enroll_and_login()
        family = AdminRefreshFamily.objects.get(user=self.user)
        original = timezone.now() - timedelta(minutes=10)
        family.last_activity_at = original
        family.save(update_fields=['last_activity_at', 'updated_at'])

        background = self.client.get('/api/v1/admin/auth/me/', **self._access_header(payload))
        self.assertEqual(background.status_code, status.HTTP_200_OK, background.data)
        family.refresh_from_db()
        self.assertEqual(family.last_activity_at, original)

        active = self.client.get(
            '/api/v1/admin/auth/me/',
            HTTP_X_ADMIN_USER_ACTIVITY='1',
            **self._access_header(payload),
        )
        self.assertEqual(active.status_code, status.HTTP_200_OK, active.data)
        family.refresh_from_db()
        self.assertGreater(family.last_activity_at, original)

    def test_idle_access_request_returns_423_and_password_unlock_rotates_both_tokens(self):
        payload, _ = self.enroll_and_login()
        old_access = payload['accessToken']
        old_refresh = self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME].value
        family = AdminRefreshFamily.objects.get(user=self.user)
        family.last_activity_at = timezone.now() - timedelta(minutes=21)
        family.save(update_fields=['last_activity_at', 'updated_at'])

        locked = self.client.get('/api/v1/admin/auth/me/', **self._access_header(payload))
        self.assertEqual(locked.status_code, 423, locked.data)
        self.assertEqual(locked.json()['code'], 'session_locked')

        wrong = self._post('/api/v1/admin/auth/unlock/', {'password': 'wrong-password'})
        self.assertEqual(wrong.status_code, status.HTTP_400_BAD_REQUEST, wrong.data)
        self.assertEqual(wrong.json()['code'], 'invalid_credentials')

        unlocked = self._post('/api/v1/admin/auth/unlock/', {'password': self.PASSWORD})
        self.assertEqual(unlocked.status_code, status.HTTP_200_OK, unlocked.data)
        unlocked_payload = unlocked.json()
        self.assertNotEqual(unlocked_payload['accessToken'], old_access)
        self.assertNotEqual(self.client.cookies[settings.ADMIN_REFRESH_COOKIE_NAME].value, old_refresh)
        family.refresh_from_db()
        self.assertIsNone(family.locked_at)
        self.assertTrue(SecurityEvent.objects.filter(event_type='ADMIN_SESSION_UNLOCKED').exists())

    def test_manual_lock_is_server_enforced(self):
        payload, _ = self.enroll_and_login()

        lock = self._post('/api/v1/admin/auth/lock/', **self._access_header(payload))
        self.assertEqual(lock.status_code, status.HTTP_200_OK, lock.data)
        denied = self.client.get('/api/v1/admin/auth/me/', **self._access_header(payload))
        self.assertEqual(denied.status_code, 423, denied.data)

    def test_step_up_updates_recent_mfa_and_refresh_preserves_timestamp(self):
        payload, _ = self.enroll_and_login()
        recovery_code = payload['recoveryCodes'][0]
        family = AdminRefreshFamily.objects.get(user=self.user)
        session = AuthSession.objects.get(refresh_family=family, status=AuthSession.Status.ACTIVE)
        stale = timezone.now() - timedelta(minutes=30)
        family.mfa_verified_at = stale
        family.save(update_fields=['mfa_verified_at', 'updated_at'])
        session.mfa_verified_at = stale
        session.save(update_fields=['mfa_verified_at', 'updated_at'])

        step_up = self._post(
            '/api/v1/admin/auth/mfa/step-up/',
            {'recoveryCode': recovery_code},
            **self._access_header(payload),
        )
        self.assertEqual(step_up.status_code, status.HTTP_200_OK, step_up.data)
        family.refresh_from_db()
        recent = family.mfa_verified_at
        self.assertGreater(recent, stale)
        self.assertEqual(len(AdminMFAProfile.objects.get(user=self.user).recovery_code_hashes), 9)

        refreshed = self._post('/api/v1/admin/auth/refresh/')
        self.assertEqual(refreshed.status_code, status.HTTP_200_OK, refreshed.data)
        family.refresh_from_db()
        self.assertEqual(family.mfa_verified_at, recent)
        new_session = AuthSession.objects.get(refresh_family=family, status=AuthSession.Status.ACTIVE)
        self.assertEqual(new_session.mfa_verified_at, recent)

    def test_existing_superuser_mfa_cannot_replay_totp_and_can_use_one_recovery_code_once(self):
        payload, secret = self.enroll_and_login()
        recovery_code = payload['recoveryCodes'][0]
        enrolled_counter = AdminMFAProfile.objects.get(user=self.user).last_totp_counter
        replayed_code = totp_code(secret, enrolled_counter)
        self._post('/api/v1/admin/auth/logout/')
        challenge = self._begin_login()
        self.assertEqual(challenge['status'], 'mfa_required')

        # Put verification exactly in the next TOTP step. The previously used
        # code remains inside the accepted clock-skew window, so only the
        # persisted monotonic counter can reject this as a replay.
        with patch(
            'apps.users.services.admin_mfa.time',
            new=SimpleNamespace(time=lambda: (enrolled_counter + 1) * 30),
        ):
            replayed_totp = self._post(
                '/api/v1/admin/auth/mfa/challenge/',
                {
                    'challengeToken': challenge['challengeToken'],
                    'code': replayed_code,
                },
            )
        self.assertEqual(replayed_totp.status_code, status.HTTP_400_BAD_REQUEST, replayed_totp.data)
        self.assertEqual(replayed_totp.json()['code'], 'mfa_code_invalid')

        recovered = self._post(
            '/api/v1/admin/auth/mfa/challenge/',
            {'challengeToken': challenge['challengeToken'], 'recoveryCode': recovery_code},
        )
        self.assertEqual(recovered.status_code, status.HTTP_200_OK, recovered.data)
        self.assertEqual(recovered.json()['status'], 'authenticated')
        profile = AdminMFAProfile.objects.get(user=self.user)
        self.assertEqual(len(profile.recovery_code_hashes), 9)
        self.assertTrue(SecurityEvent.objects.filter(event_type='ADMIN_MFA_RECOVERY_CODE_USED').exists())

    def test_totp_replay_counter_is_rejected_at_adjacent_clock_skew_boundary(self):
        secret = 'JBSWY3DPEHPK3PXP'
        used_counter = 123_456
        boundary_now = (used_counter + 1) * 30

        self.assertIsNone(
            verify_totp(
                secret,
                totp_code(secret, used_counter),
                now=boundary_now,
                last_counter=used_counter,
            )
        )
        self.assertEqual(
            verify_totp(
                secret,
                totp_code(secret, used_counter + 1),
                now=boundary_now,
                last_counter=used_counter,
            ),
            used_counter + 1,
        )

    def test_exact_totp_code_collision_is_rejected_even_at_a_later_counter(self):
        secret = 'JBSWY3DPEHPK3PXP'
        first_counter = 492
        colliding_counter = 1109
        colliding_code = totp_code(secret, first_counter)
        self.assertEqual(colliding_code, totp_code(secret, colliding_counter))

        # Counter-only replay protection would accept this rare six-digit
        # collision because the second counter is newer.
        self.assertEqual(
            verify_totp(
                secret,
                colliding_code,
                now=colliding_counter * 30,
                last_counter=first_counter,
            ),
            colliding_counter,
        )
        self.assertIsNone(
            verify_totp(
                secret,
                colliding_code,
                now=colliding_counter * 30,
                last_counter=first_counter,
                last_code_digest=totp_code_digest(secret, colliding_code),
            )
        )

    def test_repeated_step_up_failures_lock_the_refresh_family(self):
        payload, secret = self.enroll_and_login()
        current_counter = int(time()) // 30
        valid_window = {totp_code(secret, current_counter + offset) for offset in (-1, 0, 1)}
        invalid_code = next(f'{candidate:06d}' for candidate in range(1_000_000) if f'{candidate:06d}' not in valid_window)

        for attempt in range(settings.ADMIN_MFA_MAX_ATTEMPTS):
            response = self._post(
                '/api/v1/admin/auth/mfa/step-up/',
                {'code': invalid_code},
                **self._access_header(payload),
            )
            if attempt < settings.ADMIN_MFA_MAX_ATTEMPTS - 1:
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

        self.assertEqual(response.status_code, 423, response.data)
        self.assertEqual(response.json()['code'], 'session_locked')
        family = AdminRefreshFamily.objects.get(user=self.user)
        session = AuthSession.objects.get(refresh_family=family, status=AuthSession.Status.ACTIVE)
        self.assertIsNotNone(family.locked_at)
        self.assertIsNotNone(session.locked_at)
        self.assertTrue(SecurityEvent.objects.filter(event_type='ADMIN_MFA_STEP_UP_LOCKED_OUT').exists())

    def test_logout_revokes_whole_family_and_expires_host_cookie(self):
        payload, _ = self.enroll_and_login()
        family = AdminRefreshFamily.objects.get(user=self.user)

        response = self._post('/api/v1/admin/auth/logout/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        family.refresh_from_db()
        self.assertEqual(family.status, AdminRefreshFamily.Status.REVOKED)
        self.assertFalse(AuthSession.objects.filter(refresh_family=family, status=AuthSession.Status.ACTIVE).exists())
        cookie = response.cookies[settings.ADMIN_REFRESH_COOKIE_NAME]
        self.assertEqual(cookie.value, '')
        self.assertEqual(cookie['path'], '/')
        self.assertEqual(cookie['domain'], '')
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        rejected = self.client.get('/api/v1/admin/auth/me/', **self._access_header(payload))
        self.assertEqual(rejected.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_password_change_revokes_access_refresh_family_and_tokens(self):
        payload, _ = self.enroll_and_login()
        family = AdminRefreshFamily.objects.get(user=self.user)
        self.user.set_password('Another-Strong-Password-456!')
        self.user.save(update_fields=['password'])

        access = self.client.get('/api/v1/admin/auth/me/', **self._access_header(payload))
        refresh = self._post('/api/v1/admin/auth/refresh/')

        self.assertEqual(access.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(refresh.status_code, status.HTTP_401_UNAUTHORIZED)
        family.refresh_from_db()
        self.assertEqual(family.status, AdminRefreshFamily.Status.REVOKED)
        self.assertFalse(AdminRefreshToken.objects.filter(family=family, revoked_at__isnull=True).exists())

    def test_legacy_admin_access_session_without_refresh_family_cannot_bypass_new_login(self):
        token = 'legacy-opaque-access'
        AuthSession.objects.create(
            user=self.user,
            token_key_hash=AuthSession.build_token_key_hash(token),
            surface=AuthSession.Surface.ADMIN,
            expires_at=timezone.now() + timedelta(minutes=15),
            status=AuthSession.Status.ACTIVE,
        )

        response = self.client.get('/api/v1/admin/auth/me/', HTTP_AUTHORIZATION=f'Token {token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['code'], 'admin_session_upgrade_required')

    def test_exact_origin_is_required_and_rejection_is_a_security_event(self):
        cookie_endpoints = (
            ('/api/v1/admin/auth/login/', {'username': self.user.username, 'password': self.PASSWORD}),
            ('/api/v1/admin/auth/refresh/', {}),
            ('/api/v1/admin/auth/logout/', {}),
            ('/api/v1/admin/auth/unlock/', {}),
            ('/api/v1/admin/auth/mfa/enrollment/start/', {}),
            ('/api/v1/admin/auth/mfa/enrollment/confirm/', {}),
            ('/api/v1/admin/auth/mfa/challenge/', {}),
        )
        for path, payload in cookie_endpoints:
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    payload,
                    format='json',
                    HTTP_ORIGIN=f'{TEST_ORIGIN}.attacker.example',
                    REMOTE_ADDR=self.TEST_CLIENT_IP,
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
                self.assertEqual(response.json()['code'], 'origin_not_allowed')

        self.assertEqual(
            SecurityEvent.objects.filter(event_type='ADMIN_AUTH_ORIGIN_REJECTED').count(),
            len(cookie_endpoints),
        )

    def test_failed_login_lockout_is_recorded(self):
        for attempt in range(settings.ADMIN_LOGIN_MAX_FAILURES):
            response = self._post(
                '/api/v1/admin/auth/login/',
                {'username': self.user.username, 'password': f'wrong-{attempt}'},
            )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, response.data)
        self.assertEqual(response.json()['code'], 'login_locked')
        self.assertEqual(SecurityEvent.objects.filter(event_type='ADMIN_LOGIN_FAILED').count(), 4)
        self.assertEqual(SecurityEvent.objects.filter(event_type='ADMIN_LOGIN_LOCKED_OUT').count(), 1)

    def test_login_throttle_contract_remains_ip_scoped_at_ten_per_minute(self):
        throttle = LoginRateThrottle()
        request = APIRequestFactory().post('/', REMOTE_ADDR='198.51.100.25')

        self.assertEqual(throttle.rate, '10/min')
        self.assertEqual(throttle.get_cache_key(request, None), 'throttle_login_198.51.100.25')

    def test_admin_token_cannot_be_used_on_pos_surface(self):
        payload, _ = self.enroll_and_login()

        response = self.client.get('/api/v1/pos/auth/me/', **self._access_header(payload))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(
    ADMIN_MFA_REQUIRED=False,
    ADMIN_AUTH_ALLOWED_ORIGINS=[TEST_ORIGIN],
    ADMIN_MFA_FERNET_KEYS=[],
)
class PasswordOnlyAdminAuthTests(APITestCase):
    def test_superuser_login_and_refresh_use_password_only(self):
        user = User.objects.create_superuser(
            username='password-only-superadmin',
            password='Password-Only-Admin-123!',
        )
        login = self.client.post(
            '/api/v1/admin/auth/login/',
            {'username': user.username, 'password': 'Password-Only-Admin-123!'},
            format='json',
            HTTP_ORIGIN=TEST_ORIGIN,
        )

        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)
        self.assertEqual(login.json()['status'], 'authenticated')
        self.assertNotIn('challengeToken', login.json())
        self.assertFalse(AdminMFAChallenge.objects.filter(user=user).exists())
        self.assertFalse(AdminMFAProfile.objects.filter(user=user).exists())

        refresh = self.client.post('/api/v1/admin/auth/refresh/', HTTP_ORIGIN=TEST_ORIGIN)
        self.assertEqual(refresh.status_code, status.HTTP_200_OK, refresh.data)
        self.assertEqual(refresh.json()['status'], 'authenticated')

        for path in (
            '/api/v1/admin/auth/mfa/enrollment/start/',
            '/api/v1/admin/auth/mfa/enrollment/confirm/',
            '/api/v1/admin/auth/mfa/challenge/',
        ):
            response = self.client.post(path, {}, format='json', HTTP_ORIGIN=TEST_ORIGIN)
            self.assertEqual(response.status_code, status.HTTP_410_GONE, response.data)
            self.assertEqual(response.json()['code'], 'mfa_disabled')

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {refresh.json()['accessToken']}")
        step_up = self.client.post(
            '/api/v1/admin/auth/mfa/step-up/',
            {},
            format='json',
            HTTP_ORIGIN=TEST_ORIGIN,
        )
        self.assertEqual(step_up.status_code, status.HTTP_410_GONE, step_up.data)
        self.assertEqual(step_up.json()['code'], 'mfa_disabled')
