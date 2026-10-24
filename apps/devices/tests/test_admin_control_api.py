from datetime import timedelta

from django.core.cache import cache
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.devices.models import Device, DevicePairing
from apps.devices.tests import test_control_api as fixtures
from apps.users.models import AuthSession, Role, User


urlpatterns = [path('api/v1/admin/device-control/', include('apps.devices.admin_control_urls'))]
BASE = '/api/v1/admin/device-control'


@override_settings(
    ROOT_URLCONF=__name__,
    ADMIN_MFA_REQUIRED=False,
    REST_FRAMEWORK=fixtures.ControlApiTests._overridden_settings['REST_FRAMEWORK'],
)
class AdminControlApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ControlApiTests.setUpTestData.__func__(cls)

    authenticate_superuser = fixtures.ControlApiTests.authenticate_superuser
    create_device = fixtures.ControlApiTests.create_device
    create_pairing = fixtures.ControlApiTests.create_pairing

    def setUp(self):
        cache.clear()

    def test_bridge_rejects_anonymous_partner_and_product_owner(self):
        self.assertEqual(self.client.get(f'{BASE}/branches/').status_code, 401)
        owner = User.objects.create_user(username='owner-review', role=Role.objects.get(code='product_owner'))
        for user in (self.ordinary_user, self.partner_user, owner):
            self.client.force_authenticate(user=user)
            self.assertEqual(self.client.get(f'{BASE}/branches/').status_code, 403)
            self.assertEqual(self.client.post(f'{BASE}/pairings/resolve/', {}).status_code, 403)

    def test_real_admin_session_and_partner_filter_preserve_minimized_schema(self):
        self.authenticate_superuser()
        self.create_device(restaurant=self.branch)
        response = self.client.get(f'{BASE}/branches/', {'business_partner_id': str(self.partner.pk)})
        self.assertEqual(response.status_code, 200)
        rows = response.json()['data']
        self.assertEqual({row['id'] for row in rows}, {str(self.branch.pk), str(self.inactive_branch.pk)})
        self.assertEqual(set(rows[0]), fixtures.BRANCH_RESPONSE_KEYS)
        self.assertEqual(self.client.get(f'{BASE}/branches/', {'business_partner_id': 'bad'}).status_code, 400)

    def test_pos_audience_cannot_open_bridge_even_for_superuser(self):
        bundle = self.authenticate_superuser()
        AuthSession.objects.filter(pk=bundle.access_session.pk).update(surface=AuthSession.Surface.POS)
        self.assertEqual(self.client.get(f'{BASE}/branches/').status_code, 401)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_mutations_require_recent_mfa_and_do_not_change_device_on_denial(self):
        device = self.create_device(restaurant=self.branch)
        self.authenticate_superuser(recent=False)
        response = self.client.post(f'{BASE}/branches/{self.branch.pk}/devices/{device.pk}/revoke/', {'reason': 'Retired terminal'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'mfa_step_up_required')
        device.refresh_from_db()
        self.assertEqual(device.status, Device.Status.ACTIVE)
        self.authenticate_superuser(recent=True)
        result = self.client.post(f'{BASE}/branches/{self.branch.pk}/devices/{device.pk}/revoke/', {'reason': 'Retired terminal'}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(result.json()['device']), fixtures.DEVICE_RESPONSE_KEYS)

    def test_revoke_remains_branch_bound_allowlisted_and_reason_required(self):
        self.authenticate_superuser()
        device = self.create_device(restaurant=self.other_branch)
        url = f'{BASE}/branches/{self.branch.pk}/devices/{device.pk}/revoke/'
        self.assertEqual(self.client.post(url, {'reason': 'Retired terminal'}, format='json').status_code, 404)
        own = self.create_device(restaurant=self.branch)
        own_url = f'{BASE}/branches/{self.branch.pk}/devices/{own.pk}/revoke/'
        self.assertEqual(self.client.post(own_url, {'reason': 'x'}, format='json').status_code, 400)
        own.refresh_from_db()
        self.assertEqual(own.status, Device.Status.ACTIVE)

    def test_pairing_claim_expiry_code_and_single_use_are_preserved(self):
        self.authenticate_superuser()
        pairing, token = self.create_pairing()
        resolve = f'{BASE}/pairings/resolve/'
        self.assertEqual(self.client.post(resolve, {'pairingId': str(pairing.pk), 'claimToken': 'x' * 48}, format='json').status_code, 400)
        result = self.client.post(resolve, {'pairingId': str(pairing.pk), 'claimToken': token}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(result.json()['pairing']), fixtures.PAIRING_RESPONSE_KEYS)
        decision = f'{BASE}/branches/{self.branch.pk}/pairings/{pairing.pk}/reject/'
        payload = {'claimToken': token, 'displayCode': '000000'}
        self.assertEqual(self.client.post(decision, payload, format='json').status_code, 400)
        payload['displayCode'] = '481209'
        self.assertEqual(self.client.post(decision, payload, format='json').status_code, 200)
        self.assertEqual(self.client.post(decision, payload, format='json').status_code, 400)
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, DevicePairing.Status.REJECTED)
        expired, expired_token = self.create_pairing(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post(resolve, {'pairingId': str(expired.pk), 'claimToken': expired_token}, format='json').status_code, 400)

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_pairing_decision_requires_recent_mfa_before_consuming_request(self):
        self.authenticate_superuser(recent=False)
        pairing, token = self.create_pairing()
        response = self.client.post(f'{BASE}/branches/{self.branch.pk}/pairings/{pairing.pk}/approve/', {'claimToken': token, 'displayCode': '481209', 'name': 'Front POS'}, format='json')
        self.assertEqual(response.status_code, 403)
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, DevicePairing.Status.PENDING)
        self.assertIsNone(pairing.device_id)

    @override_settings(ADMIN_MFA_REQUIRED=True, TELEGRAM_REPORTS_BOT_USERNAME='test_reports_bot')
    def test_telegram_link_requires_recent_mfa_and_rejects_inactive_branch(self):
        self.authenticate_superuser(recent=False)
        self.assertEqual(self.client.post(f'{BASE}/branches/{self.branch.pk}/telegram-link/', {}, format='json').status_code, 403)
        self.authenticate_superuser(recent=True)
        self.assertEqual(self.client.post(f'{BASE}/branches/{self.inactive_branch.pk}/telegram-link/', {}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f'{BASE}/branches/{self.branch.pk}/telegram-link/', {}, format='json').status_code, 201)
