from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, local
from time import sleep
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.platform.models import RestaurantEntitlement, Tariff
from apps.restaurants.models import Restaurant
from apps.users.models import AuthSession, Role, StaffInvite, StaffRefreshFamily, StaffRefreshToken, User
from apps.users.services.staff_auth import REFRESH_RACE_GRACE, StaffAuthError, StaffAuthService


ORIGIN = 'http://localhost:4600'
PASSWORD = 'A-strong-staff-password-2026!'


@override_settings(STAFF_AUTH_ALLOWED_ORIGINS=[ORIGIN])
class StaffAuthTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Staff test restaurant', is_active=True)
        cls.other_restaurant = Restaurant.objects.create(name='Other staff restaurant', is_active=True)
        cls.admin_role = Role.objects.get(code='restaurant_admin')
        cls.waiter_role = Role.objects.get(code='waiter')
        tariff = Tariff.objects.create(name='Staff test tariff', is_active=True)
        tariff.allowed_roles.set([cls.admin_role, cls.waiter_role])
        tariff.permissions.set([
            *cls.admin_role.permissions.all(),
            *cls.waiter_role.permissions.all(),
        ])
        RestaurantEntitlement.objects.create(restaurant=cls.restaurant, tariff=tariff, is_active=True)
        RestaurantEntitlement.objects.create(restaurant=cls.other_restaurant, tariff=tariff, is_active=True)
        cls.admin = User.objects.create_user(
            username='staff-admin', password='admin-strong-2026!', full_name='Staff Admin',
            restaurant=cls.restaurant, role=cls.admin_role,
        )
        cls.employee = User.objects.create_user(
            username='staff-waiter', full_name='Staff Waiter',
            restaurant=cls.restaurant, role=cls.waiter_role,
        )
        cls.employee.set_pin('1234')
        cls.employee.save(update_fields=['pin_code'])
        cls.other_employee = User.objects.create_user(
            username='other-staff-waiter', full_name='Other Waiter',
            restaurant=cls.other_restaurant, role=cls.waiter_role,
        )

    def setUp(self):
        cache.clear()

    def post_staff(self, path, payload=None, **extra):
        return self.client.post(path, payload or {}, format='json', HTTP_ORIGIN=ORIGIN, **extra)

    def issue_invite(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/v1/admin/employees/{self.employee.pk}/staff-invite/', {}, format='json')
        self.client.force_authenticate(user=None)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.json()['inviteUrl'].startswith(f'{settings.STAFF_PWA_PUBLIC_ORIGIN}/invite/'))
        return response.json()['token']

    def test_one_time_invite_sets_password_without_using_pos_pin(self):
        failed = self.post_staff('/api/v1/staff/auth/login/', {'username': self.employee.username, 'password': '1234'})
        self.assertEqual(failed.status_code, 401)
        token = self.issue_invite()
        self.assertNotEqual(StaffInvite.objects.get(user=self.employee).token_hash, token)
        accepted = self.post_staff('/api/v1/staff/auth/invite/accept/', {'token': token, 'password': PASSWORD})
        self.assertEqual(accepted.status_code, 200, accepted.data)
        access = accepted.json()['accessToken']
        self.assertIn(settings.STAFF_REFRESH_COOKIE_NAME, self.client.cookies)
        self.assertTrue(self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME]['httponly'])
        me = self.client.get('/api/v1/staff/auth/me/', HTTP_AUTHORIZATION=f'Token {access}')
        self.assertEqual(me.status_code, 200, me.data)
        self.assertEqual(me.json()['user']['username'], self.employee.username)
        reused_invite = self.post_staff('/api/v1/staff/auth/invite/accept/', {'token': token, 'password': PASSWORD})
        self.assertEqual(reused_invite.status_code, 400)

    def test_refresh_rotation_replay_revokes_family_and_access(self):
        token = self.issue_invite()
        accepted = self.post_staff('/api/v1/staff/auth/invite/accept/', {'token': token, 'password': PASSWORD})
        old_refresh = self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME].value
        first_access = accepted.json()['accessToken']
        rotated = self.post_staff('/api/v1/staff/auth/refresh/')
        self.assertEqual(rotated.status_code, 200, rotated.data)
        current_refresh = self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME] = old_refresh
        raced = self.post_staff('/api/v1/staff/auth/refresh/')
        self.assertEqual(raced.status_code, 409)
        self.assertEqual(raced.json()['code'], 'refresh_raced')
        self.assertNotIn('accessToken', raced.json())
        self.assertNotIn(settings.STAFF_REFRESH_COOKIE_NAME, raced.cookies)
        self.assertEqual(StaffRefreshFamily.objects.get(user=self.employee).status, StaffRefreshFamily.Status.ACTIVE)

        self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME] = current_refresh
        next_rotation = self.post_staff('/api/v1/staff/auth/refresh/')
        self.assertEqual(next_rotation.status_code, 200, next_rotation.data)

        StaffRefreshToken.objects.filter(token_hash=StaffRefreshToken.hash_token(old_refresh)).update(
            used_at=timezone.now() - REFRESH_RACE_GRACE - timedelta(seconds=1),
        )
        self.client.cookies[settings.STAFF_REFRESH_COOKIE_NAME] = old_refresh
        replay = self.post_staff('/api/v1/staff/auth/refresh/')
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json()['code'], 'refresh_reused')
        self.assertEqual(StaffRefreshFamily.objects.get(user=self.employee).status, StaffRefreshFamily.Status.REVOKED)
        self.assertFalse(AuthSession.objects.filter(user=self.employee, status=AuthSession.Status.ACTIVE).exists())
        denied = self.client.get('/api/v1/staff/auth/me/', HTTP_AUTHORIZATION=f'Token {first_access}')
        self.assertEqual(denied.status_code, 401)

    def test_admin_cannot_invite_another_restaurants_employee(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/v1/admin/employees/{self.other_employee.pk}/staff-invite/', {}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(StaffInvite.objects.filter(user=self.other_employee).exists())

    def test_staff_credentials_require_exact_origin(self):
        self.issue_invite()
        response = self.client.post('/api/v1/staff/auth/login/', {
            'username': self.employee.username, 'password': PASSWORD,
        }, format='json', HTTP_ORIGIN='https://evil.example')
        self.assertEqual(response.status_code, 403)


class StaffRefreshConcurrencyTests(TransactionTestCase):
    def test_simultaneous_refreshes_of_separate_families_keep_both_sessions(self):
        restaurant = Restaurant.objects.create(name='Refresh concurrency restaurant', is_active=True)
        role = Role.objects.get(code='waiter')
        tariff = Tariff.objects.create(name='Refresh concurrency tariff', is_active=True)
        tariff.allowed_roles.set([role])
        RestaurantEntitlement.objects.create(restaurant=restaurant, tariff=tariff, is_active=True)
        factory = RequestFactory()
        service = StaffAuthService()
        credentials = []
        for index in range(2):
            user = User.objects.create_user(
                username=f'concurrent-staff-{index}', password=PASSWORD,
                full_name=f'Concurrent Staff {index}', restaurant=restaurant, role=role,
            )
            credentials.append(service.issue_credentials(user=user, request=factory.post('/staff/auth/login/')))

        barrier = Barrier(2)
        thread_state = local()
        original_create = StaffRefreshToken.objects.create

        def create_after_both_transactions_have_read(**kwargs):
            if not getattr(thread_state, 'reached_barrier', False):
                thread_state.reached_barrier = True
                barrier.wait(timeout=5)
            return original_create(**kwargs)

        def rotate(bundle):
            close_old_connections()
            try:
                return StaffAuthService().rotate_refresh(
                    raw_token=bundle.refresh_token,
                    request=factory.post('/staff/auth/refresh/'),
                )
            finally:
                connection.close()

        with mock.patch.object(StaffRefreshToken.objects, 'create', side_effect=create_after_both_transactions_have_read):
            with mock.patch('apps.users.services.staff_auth.sleep', wraps=sleep) as retry_sleep:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    rotated = list(executor.map(rotate, credentials))

        self.assertEqual(len(rotated), 2)
        if connection.vendor == 'sqlite':
            self.assertGreaterEqual(retry_sleep.call_count, 1)
        self.assertTrue(all(bundle.access_token != previous.access_token for bundle, previous in zip(rotated, credentials)))
        self.assertEqual(
            StaffRefreshFamily.objects.filter(status=StaffRefreshFamily.Status.ACTIVE).count(), 2,
        )
        self.assertEqual(StaffRefreshToken.objects.filter(used_at__isnull=False).count(), 2)

    def test_simultaneous_refreshes_of_same_cookie_allow_one_rotation_without_revoking_family(self):
        restaurant = Restaurant.objects.create(name='Same-cookie restaurant', is_active=True)
        role = Role.objects.get(code='waiter')
        tariff = Tariff.objects.create(name='Same-cookie tariff', is_active=True)
        tariff.allowed_roles.set([role])
        RestaurantEntitlement.objects.create(restaurant=restaurant, tariff=tariff, is_active=True)
        user = User.objects.create_user(
            username='same-cookie-staff', password=PASSWORD,
            full_name='Same Cookie Staff', restaurant=restaurant, role=role,
        )
        factory = RequestFactory()
        original = StaffAuthService().issue_credentials(user=user, request=factory.post('/staff/auth/login/'))
        barrier = Barrier(2)

        def rotate():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return StaffAuthService().rotate_refresh(
                        raw_token=original.refresh_token,
                        request=factory.post('/staff/auth/refresh/'),
                    )
                except StaffAuthError as exc:
                    return exc
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: rotate(), range(2)))

        self.assertEqual(sum(not isinstance(result, StaffAuthError) for result in outcomes), 1)
        errors = [result for result in outcomes if isinstance(result, StaffAuthError)]
        self.assertEqual([error.code for error in errors], ['refresh_raced'])
        self.assertEqual([error.http_status for error in errors], [409])
        self.assertEqual(StaffRefreshFamily.objects.get(pk=original.refresh_family.pk).status, StaffRefreshFamily.Status.ACTIVE)
        self.assertEqual(StaffRefreshToken.objects.filter(family=original.refresh_family).count(), 2)
