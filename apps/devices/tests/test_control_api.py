import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.devices.control_serializers import masked_fingerprint
from apps.devices.control_services import (
    CONTROL_PAIRING_MAX_FAILURES,
    ControlPairingAttemptsExceeded,
    reserve_control_pairing_attempt,
)
from apps.devices.models import Device, DevicePairing, SecurityEvent, hash_device_secret
from apps.platform.models import BusinessPartner
from apps.restaurants.models import Restaurant
from apps.telegram_reports.models import TelegramAccount, TelegramBranchSubscription, TelegramLinkToken
from apps.users.models import Role, User
from apps.users.services import AdminAuthService


PAIRING_RESPONSE_KEYS = {
    'id',
    'deviceType',
    'requestedName',
    'platform',
    'appVersion',
    'expiresAt',
    'fingerprintHint',
    'displayCodeLength',
}
BRANCH_RESPONSE_KEYS = {
    'id',
    'name',
    'address',
    'isActive',
    'activeDeviceCount',
    'revokedDeviceCount',
    'lastSeenAt',
}
DEVICE_RESPONSE_KEYS = {
    'id',
    'type',
    'name',
    'platform',
    'appVersion',
    'status',
    'lastSeenAt',
    'pairedAt',
    'revokedAt',
    'revokeReason',
    'fingerprintHint',
}


@override_settings(
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': (
            'common.api.authentication.ExpiringSessionTokenAuthentication',
        ),
        'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
        'DEFAULT_RENDERER_CLASSES': (
            'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
        ),
        'DEFAULT_PARSER_CLASSES': (
            'djangorestframework_camel_case.parser.CamelCaseJSONParser',
        ),
        'DEFAULT_PAGINATION_CLASS': 'common.api.paginations.Pagination',
        'PAGE_SIZE': 10,
        'DEFAULT_THROTTLE_RATES': {
            'control_pairing_resolve': '1000/min',
            'control_pairing_decision': '1000/min',
        },
    }
)
class ControlApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='control-api-superuser',
            password='Control-API-Strong-Password-123!',
            full_name='Control API Superuser',
        )
        cls.ordinary_user = User.objects.create_user(
            username='control-api-ordinary',
            password='Control-API-Ordinary-Password-123!',
            full_name='Control API Ordinary User',
        )
        cls.branch = Restaurant.objects.create(
            name='Alpha Branch',
            address='Tashkent, Yunusabad',
            is_active=True,
        )
        cls.other_branch = Restaurant.objects.create(
            name='Beta Branch',
            address='Samarkand',
            is_active=True,
        )
        cls.inactive_branch = Restaurant.objects.create(
            name='Closed Branch',
            address='Bukhara',
            is_active=False,
        )
        cls.partner = BusinessPartner.objects.create(
            inn='309999999',
            company_name='Scoped Partner',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.other_partner = BusinessPartner.objects.create(
            inn='308888888',
            company_name='Other Partner',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.branch.business_partner = cls.partner
        cls.branch.save(update_fields=['business_partner', 'updated_at'])
        cls.inactive_branch.business_partner = cls.partner
        cls.inactive_branch.save(update_fields=['business_partner', 'updated_at'])
        cls.other_branch.business_partner = cls.other_partner
        cls.other_branch.save(update_fields=['business_partner', 'updated_at'])
        cls.partner_user = User.objects.create_user(
            username='control-partner',
            password='Control-Partner-Password-123!',
            full_name='Control Partner',
            role=Role.objects.get(code='business_partner'),
            business_partner=cls.partner,
        )

    def setUp(self):
        cache.clear()
        self.client.credentials()
        self.client.force_authenticate(user=None)

    def force_superuser(self):
        self.client.force_authenticate(user=self.superuser)

    def authenticate_superuser(self, *, recent=True):
        verified_at = timezone.now() if recent else timezone.now() - timedelta(minutes=16)
        request = APIRequestFactory().post(
            '/',
            HTTP_ORIGIN='https://admin.cafe-postcode.uz',
            REMOTE_ADDR='192.0.2.90',
        )
        bundle = AdminAuthService().issue_credentials(
            user=self.superuser,
            request=request,
            mfa_verified_at=verified_at,
        )
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {bundle.access_token}')
        return bundle

    def create_device(
        self,
        *,
        restaurant=None,
        device_type=Device.Type.POS_TERMINAL,
        device_status=Device.Status.ACTIVE,
        name='POS 1',
        fingerprint=None,
        last_seen_at=None,
    ):
        now = timezone.now()
        fingerprint = fingerprint or uuid.uuid4().hex + uuid.uuid4().hex
        revoked = device_status == Device.Status.REVOKED
        return Device.objects.create(
            restaurant=restaurant,
            type=device_type,
            name=name,
            platform='Windows',
            app_version='2.4.0',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key=f'public-{fingerprint}',
            public_key_fingerprint=fingerprint,
            status=device_status,
            capabilities=['must-not-leak'],
            metadata={'must': 'not-leak'},
            paired_by=self.superuser,
            paired_at=now - timedelta(days=2),
            lease_expires_at=now + timedelta(hours=24),
            last_seen_at=last_seen_at or now,
            revoked_at=now - timedelta(hours=1) if revoked else None,
            revoked_by=self.superuser if revoked else None,
            revoke_reason='Retired terminal' if revoked else '',
        )

    def create_pairing(
        self,
        *,
        device_type=Device.Type.POS_TERMINAL,
        claim_token=None,
        display_code='481209',
        expires_at=None,
        pairing_status=DevicePairing.Status.PENDING,
    ):
        claim_token = claim_token or f'claim-{uuid.uuid4().hex}-{uuid.uuid4().hex}'
        fingerprint = uuid.uuid4().hex + uuid.uuid4().hex
        pairing = DevicePairing.objects.create(
            device_type=device_type,
            requested_name='Front counter',
            platform='Windows',
            app_version='2.4.0',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key=f'public-{fingerprint}',
            public_key_fingerprint=fingerprint,
            poll_token_hash=hash_device_secret(f'poll-{uuid.uuid4().hex}-{uuid.uuid4().hex}'),
            claim_token_hash=hash_device_secret(claim_token),
            display_code=display_code,
            status=pairing_status,
            expires_at=expires_at or timezone.now() + timedelta(minutes=5),
        )
        return pairing, claim_token

    def test_control_endpoints_require_authenticated_control_operator(self):
        anonymous = self.client.get('/api/v1/admin/control/branches/')
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.ordinary_user)
        forbidden = self.client.get('/api/v1/admin/control/branches/')
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_business_partner_sees_and_controls_only_assigned_restaurants_without_mfa(self):
        own_device = self.create_device(restaurant=self.branch, name='Partner POS')
        foreign_device = self.create_device(restaurant=self.other_branch, name='Foreign POS')
        self.client.force_authenticate(user=self.partner_user)

        branches = self.client.get('/api/v1/admin/control/branches/')
        self.assertEqual(branches.status_code, status.HTTP_200_OK, branches.data)
        returned_ids = {item['id'] for item in branches.json()['data']}
        self.assertEqual(returned_ids, {str(self.branch.pk), str(self.inactive_branch.pk)})

        own_devices = self.client.get(f'/api/v1/admin/control/branches/{self.branch.pk}/devices/')
        self.assertEqual(own_devices.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in own_devices.json()['data']], [str(own_device.pk)])

        foreign_devices = self.client.get(f'/api/v1/admin/control/branches/{self.other_branch.pk}/devices/')
        self.assertEqual(foreign_devices.status_code, status.HTTP_200_OK)
        self.assertEqual(foreign_devices.json()['data'], [])

        foreign_revoke = self.client.post(
            f'/api/v1/admin/control/branches/{self.other_branch.pk}/devices/{foreign_device.pk}/revoke/',
            {'reason': 'Must remain scoped'},
            format='json',
        )
        self.assertEqual(foreign_revoke.status_code, status.HTTP_404_NOT_FOUND)
        foreign_device.refresh_from_db()
        self.assertEqual(foreign_device.status, Device.Status.ACTIVE)

        own_revoke = self.client.post(
            f'/api/v1/admin/control/branches/{self.branch.pk}/devices/{own_device.pk}/revoke/',
            {'reason': 'Partner requested revoke'},
            format='json',
        )
        self.assertEqual(own_revoke.status_code, status.HTTP_200_OK, own_revoke.data)
        own_device.refresh_from_db()
        self.assertEqual(own_device.status, Device.Status.REVOKED)

    @override_settings(TELEGRAM_REPORTS_BOT_USERNAME='postcode_reports_bot')
    def test_business_partner_lists_and_issues_telegram_links_only_for_own_branch(self):
        own_account = TelegramAccount.objects.create(
            telegram_user_id=101,
            chat_id=101,
            username='own_operator',
            first_name='Own',
        )
        foreign_account = TelegramAccount.objects.create(
            telegram_user_id=202,
            chat_id=202,
            username='foreign_operator',
            first_name='Foreign',
        )
        own = TelegramBranchSubscription.objects.create(account=own_account, restaurant=self.branch)
        TelegramBranchSubscription.objects.create(account=foreign_account, restaurant=self.other_branch)
        self.client.force_authenticate(user=self.partner_user)

        listed = self.client.get(
            f'/api/v1/admin/control/branches/{self.branch.pk}/telegram-subscriptions/'
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.data)
        self.assertEqual(listed.json()['total'], 1)
        self.assertEqual(
            set(listed.json()['data'][0]),
            {'id', 'telegramUserId', 'username', 'firstName', 'notificationsEnabled', 'linkedAt'},
        )
        self.assertEqual(listed.json()['data'][0]['id'], str(own.pk))
        self.assertNotIn('chatId', json.dumps(listed.json()))

        foreign = self.client.get(
            f'/api/v1/admin/control/branches/{self.other_branch.pk}/telegram-subscriptions/'
        )
        self.assertEqual(foreign.status_code, status.HTTP_200_OK)
        self.assertEqual(foreign.json()['data'], [])

        issued = self.client.post(
            f'/api/v1/admin/control/branches/{self.branch.pk}/telegram-link/',
            {},
            format='json',
        )
        self.assertEqual(issued.status_code, status.HTTP_201_CREATED, issued.data)
        self.assertEqual(
            set(issued.json()),
            {'id', 'restaurantId', 'restaurantName', 'startUrl', 'expiresAt'},
        )
        self.assertTrue(issued.json()['startUrl'].startswith('https://t.me/postcode_reports_bot?start='))
        token = TelegramLinkToken.objects.get(pk=issued.json()['id'])
        self.assertEqual(token.restaurant, self.branch)
        self.assertEqual(token.issued_by, self.partner_user)

        revoked = self.client.post(
            f'/api/v1/admin/control/branches/{self.branch.pk}/telegram-subscriptions/{own.pk}/revoke/',
            {},
            format='json',
        )
        self.assertEqual(revoked.status_code, status.HTTP_204_NO_CONTENT, revoked.data)
        self.assertFalse(TelegramBranchSubscription.objects.filter(pk=own.pk).exists())

        denied = self.client.post(
            f'/api/v1/admin/control/branches/{self.other_branch.pk}/telegram-link/',
            {},
            format='json',
        )
        self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(TelegramLinkToken.objects.filter(restaurant=self.other_branch).exists())

        denied_revoke = self.client.post(
            f'/api/v1/admin/control/branches/{self.other_branch.pk}/telegram-subscriptions/'
            f'{TelegramBranchSubscription.objects.get(restaurant=self.other_branch).pk}/revoke/',
            {},
            format='json',
        )
        self.assertEqual(denied_revoke.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(TelegramBranchSubscription.objects.filter(restaurant=self.other_branch).exists())

    @override_settings(
        ADMIN_AUTH_ALLOWED_ORIGINS=['https://admin.example.test'],
        ADMIN_MFA_REQUIRED=False,
    )
    def test_business_partner_password_login_can_open_scoped_control(self):
        login = self.client.post(
            '/api/v1/admin/auth/login/',
            {
                'username': self.partner_user.username,
                'password': 'Control-Partner-Password-123!',
            },
            format='json',
            HTTP_ORIGIN='https://admin.example.test',
            REMOTE_ADDR='192.0.2.44',
        )

        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)
        self.assertEqual(login.json()['status'], 'authenticated')
        self.assertNotIn('challengeToken', login.json())

        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {login.json()['accessToken']}")
        branches = self.client.get('/api/v1/admin/control/branches/')

        self.assertEqual(branches.status_code, status.HTTP_200_OK, branches.data)
        self.assertEqual(
            {item['id'] for item in branches.json()['data']},
            {str(self.branch.pk), str(self.inactive_branch.pk)},
        )

    def test_inactive_business_partner_is_denied(self):
        self.partner.status = BusinessPartner.Status.INACTIVE
        self.partner.save(update_fields=['status', 'updated_at'])
        self.client.force_authenticate(user=self.partner_user)

        response = self.client.get('/api/v1/admin/control/branches/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_branch_list_is_paginated_searchable_filterable_ordered_and_data_minimized(self):
        newest = timezone.now()
        self.create_device(restaurant=self.branch, name='Alpha POS', last_seen_at=newest)
        self.create_device(
            restaurant=self.branch,
            name='Old POS',
            device_status=Device.Status.REVOKED,
            last_seen_at=newest - timedelta(days=1),
        )
        self.create_device(
            restaurant=self.branch,
            device_type=Device.Type.CONTROL_DEVICE,
            name='Excluded branch control device',
        )
        self.create_device(
            restaurant=None,
            device_type=Device.Type.CONTROL_DEVICE,
            name='Excluded branchless control device',
        )
        self.force_superuser()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                '/api/v1/admin/control/branches/',
                {'search': 'yunus', 'connection_status': 'connected', 'ordering': '-lastSeenAt'},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertLessEqual(len(queries), 3)
        self.assertEqual(set(response.json()), {'page', 'pageSize', 'count', 'total', 'pagesCount', 'data'})
        self.assertEqual(response.json()['total'], 1)
        branch = response.json()['data'][0]
        self.assertEqual(set(branch), BRANCH_RESPONSE_KEYS)
        self.assertEqual(branch['id'], str(self.branch.pk))
        self.assertEqual(branch['activeDeviceCount'], 1)
        self.assertEqual(branch['revokedDeviceCount'], 1)

        disconnected = self.client.get(
            '/api/v1/admin/control/branches/',
            {'connection_status': 'not_connected'},
        )
        self.assertEqual(
            [row['id'] for row in disconnected.json()['data']],
            [str(self.other_branch.pk)],
        )
        inactive = self.client.get(
            '/api/v1/admin/control/branches/',
            {'connection_status': 'inactive'},
        )
        self.assertEqual([row['id'] for row in inactive.json()['data']], [str(self.inactive_branch.pk)])

        paged = self.client.get('/api/v1/admin/control/branches/', {'page_size': 2, 'ordering': 'name'})
        self.assertEqual(paged.json()['pageSize'], 2)
        self.assertEqual(paged.json()['count'], 2)
        self.assertEqual(paged.json()['total'], 3)
        self.assertEqual(paged.json()['pagesCount'], 2)

    def test_branch_devices_are_tenant_scoped_type_allowlisted_and_strictly_redacted(self):
        fingerprint = 'a' * 64
        visible = self.create_device(restaurant=self.branch, fingerprint=fingerprint)
        self.create_device(restaurant=self.other_branch, name='Foreign POS')
        self.create_device(
            restaurant=self.branch,
            device_type=Device.Type.CONTROL_DEVICE,
            name='Hidden Control',
        )
        self.force_superuser()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                f'/api/v1/admin/control/branches/{self.branch.pk}/devices/',
                {'ordering': '-last_seen_at'},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertLessEqual(len(queries), 3)
        self.assertEqual(response.json()['total'], 1)
        device = response.json()['data'][0]
        self.assertEqual(set(device), DEVICE_RESPONSE_KEYS)
        self.assertEqual(device['id'], str(visible.pk))
        self.assertEqual(device['fingerprintHint'], masked_fingerprint(fingerprint))
        serialized = json.dumps(response.json())
        self.assertNotIn(fingerprint, serialized)
        for forbidden_key in (
            'publicKey',
            'publicKeyAlgorithm',
            'capabilities',
            'metadata',
            'leaseExpiresAt',
            'createdAt',
        ):
            self.assertNotIn(forbidden_key, serialized)

    def test_resolve_requires_live_allowed_claim_and_never_returns_display_code_or_token(self):
        pairing, claim_token = self.create_pairing()
        self.force_superuser()
        response = self.client.post(
            '/api/v1/admin/control/pairings/resolve/',
            {'pairingId': str(pairing.pk), 'claimToken': claim_token},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(set(response.json()), {'pairing'})
        resolved = response.json()['pairing']
        self.assertEqual(set(resolved), PAIRING_RESPONSE_KEYS)
        self.assertEqual(resolved['displayCodeLength'], 6)
        serialized = json.dumps(response.json())
        self.assertNotIn(pairing.display_code, serialized)
        self.assertNotIn(claim_token, serialized)
        self.assertNotIn(pairing.public_key_fingerprint, serialized)

        invalid_payload = {'code': 'pairing_invalid', 'detail': 'Pairing request is invalid.'}
        cache.clear()
        wrong = self.client.post(
            '/api/v1/admin/control/pairings/resolve/',
            {'pairingId': str(pairing.pk), 'claimToken': 'x' * 43},
            format='json',
        )
        self.assertEqual(wrong.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(wrong.json(), invalid_payload)

        expired_pairing, expired_token = self.create_pairing(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        expired = self.client.post(
            '/api/v1/admin/control/pairings/resolve/',
            {'pairingId': str(expired_pairing.pk), 'claimToken': expired_token},
            format='json',
        )
        self.assertEqual(expired.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(expired.json(), invalid_payload)

        unsupported, unsupported_token = self.create_pairing(device_type=Device.Type.CONTROL_DEVICE)
        unsupported_response = self.client.post(
            '/api/v1/admin/control/pairings/resolve/',
            {'pairingId': str(unsupported.pk), 'claimToken': unsupported_token},
            format='json',
        )
        self.assertEqual(unsupported_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unsupported_response.json(), invalid_payload)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_pairing_approve_requires_recent_mfa_when_rollback_flag_is_enabled(self):
        pairing, claim_token = self.create_pairing()
        approve_url = (
            f'/api/v1/admin/control/branches/{self.branch.pk}/pairings/{pairing.pk}/approve/'
        )
        payload = {'claimToken': claim_token, 'displayCode': pairing.display_code, 'name': 'Main POS'}

        self.authenticate_superuser(recent=False)
        stale = self.client.post(approve_url, payload, format='json')
        self.assertEqual(stale.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(stale.json()['code'], 'mfa_step_up_required')

        self.authenticate_superuser(recent=True)
        wrong_code = self.client.post(
            approve_url,
            {**payload, 'displayCode': '000000'},
            format='json',
        )
        self.assertEqual(wrong_code.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(wrong_code.json()['code'], 'pairing_invalid')
        failure = SecurityEvent.objects.get(event_type='CONTROL_PAIRING_VERIFICATION_FAILED')
        event_json = json.dumps(failure.metadata)
        self.assertNotIn(claim_token, event_json)
        self.assertNotIn('000000', event_json)

        approved = self.client.post(approve_url, payload, format='json')
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        self.assertEqual(set(approved.json()), {'status', 'device'})
        self.assertEqual(approved.json()['status'], 'paired')
        self.assertEqual(set(approved.json()['device']), DEVICE_RESPONSE_KEYS)
        device = Device.objects.get(pk=approved.json()['device']['id'])
        self.assertEqual(device.restaurant, self.branch)
        self.assertEqual(device.type, Device.Type.POS_TERMINAL)
        approved_event = SecurityEvent.objects.get(event_type='DEVICE_PAIRING_APPROVED')
        self.assertEqual(approved_event.restaurant, self.branch)
        self.assertEqual(approved_event.actor, self.superuser)
        self.assertEqual(approved_event.device, device)
        self.assertTrue(approved_event.request_id)
        self.assertIsNotNone(approved_event.client_ip)

        replay = self.client.post(approve_url, payload, format='json')
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(replay.json()['code'], 'pairing_invalid')
        self.assertEqual(Device.objects.filter(public_key_fingerprint=pairing.public_key_fingerprint).count(), 1)

    def test_pairing_decision_has_per_pair_attempt_budget_and_sanitized_events(self):
        pairing, claim_token = self.create_pairing()
        self.authenticate_superuser(recent=True)
        url = f'/api/v1/admin/control/branches/{self.branch.pk}/pairings/{pairing.pk}/approve/'

        responses = [
            self.client.post(
                url,
                {'claimToken': claim_token, 'displayCode': f'{index:06d}', 'name': 'POS'},
                format='json',
            )
            for index in range(5)
        ]
        self.assertEqual([item.status_code for item in responses], [400, 400, 400, 400, 429])
        blocked = self.client.post(
            url,
            {'claimToken': claim_token, 'displayCode': pairing.display_code, 'name': 'POS'},
            format='json',
        )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(Device.objects.filter(public_key_fingerprint=pairing.public_key_fingerprint).exists())
        event = SecurityEvent.objects.get(event_type='CONTROL_PAIRING_ATTEMPTS_EXCEEDED')
        serialized = json.dumps(event.metadata)
        self.assertNotIn(claim_token, serialized)
        for index in range(5):
            self.assertNotIn(f'{index:06d}', serialized)

    def test_pairing_attempt_budget_is_atomic_under_parallel_reservations(self):
        pairing_id = uuid.uuid4()

        def reserve(_):
            try:
                return reserve_control_pairing_attempt(pairing_id, phase='decision')
            except ControlPairingAttemptsExceeded:
                return None

        with ThreadPoolExecutor(max_workers=16) as executor:
            reservations = list(executor.map(reserve, range(32)))

        accepted = sorted(value for value in reservations if value is not None)
        self.assertEqual(accepted, list(range(1, CONTROL_PAIRING_MAX_FAILURES + 1)))
        self.assertEqual(len(reservations) - len(accepted), 32 - CONTROL_PAIRING_MAX_FAILURES)

    def test_pairing_reject_is_branch_bound_code_verified_recent_mfa_and_single_use(self):
        pairing, claim_token = self.create_pairing()
        self.authenticate_superuser(recent=True)
        url = f'/api/v1/admin/control/branches/{self.branch.pk}/pairings/{pairing.pk}/reject/'
        payload = {'claimToken': claim_token, 'displayCode': pairing.display_code}

        rejected = self.client.post(url, payload, format='json')
        self.assertEqual(rejected.status_code, status.HTTP_200_OK, rejected.data)
        self.assertEqual(rejected.json(), {'status': 'rejected'})
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, DevicePairing.Status.REJECTED)
        rejected_event = SecurityEvent.objects.get(event_type='DEVICE_PAIRING_REJECTED')
        self.assertEqual(rejected_event.restaurant, self.branch)
        self.assertEqual(rejected_event.actor, self.superuser)
        self.assertTrue(rejected_event.request_id)
        self.assertIsNotNone(rejected_event.client_ip)

        replay = self.client.post(url, payload, format='json')
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(replay.json()['code'], 'pairing_invalid')

    def test_revoke_is_branch_scoped_type_allowlisted_recent_mfa_and_data_minimized(self):
        own_device = self.create_device(restaurant=self.branch)
        foreign_device = self.create_device(restaurant=self.other_branch, name='Foreign POS')
        control_device = self.create_device(
            restaurant=self.branch,
            device_type=Device.Type.CONTROL_DEVICE,
            name='Control Device',
        )
        self.authenticate_superuser(recent=True)
        base = f'/api/v1/admin/control/branches/{self.branch.pk}/devices'
        reason = 'Terminal was retired'

        foreign = self.client.post(
            f'{base}/{foreign_device.pk}/revoke/',
            {'reason': reason},
            format='json',
        )
        random = self.client.post(
            f'{base}/{uuid.uuid4()}/revoke/',
            {'reason': reason},
            format='json',
        )
        unsupported = self.client.post(
            f'{base}/{control_device.pk}/revoke/',
            {'reason': reason},
            format='json',
        )
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(random.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unsupported.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), random.json())
        self.assertEqual(unsupported.json(), random.json())

        revoked = self.client.post(
            f'{base}/{own_device.pk}/revoke/',
            {'reason': reason},
            format='json',
        )
        self.assertEqual(revoked.status_code, status.HTTP_200_OK, revoked.data)
        self.assertEqual(set(revoked.json()), {'device'})
        self.assertEqual(set(revoked.json()['device']), DEVICE_RESPONSE_KEYS)
        own_device.refresh_from_db()
        self.assertEqual(own_device.status, Device.Status.REVOKED)
        self.assertEqual(own_device.revoke_reason, reason)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_revoke_with_stale_mfa_is_denied_when_rollback_flag_is_enabled(self):
        device = self.create_device(restaurant=self.branch)
        self.authenticate_superuser(recent=False)
        response = self.client.post(
            f'/api/v1/admin/control/branches/{self.branch.pk}/devices/{device.pk}/revoke/',
            {'reason': 'Terminal was retired'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['code'], 'mfa_step_up_required')
        device.refresh_from_db()
        self.assertEqual(device.status, Device.Status.ACTIVE)
