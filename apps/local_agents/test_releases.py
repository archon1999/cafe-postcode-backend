import base64
import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.local_agents.admin_views import (
    LocalAgentFleetBulkActionView,
    LocalAgentFleetDiagnosticsView,
    LocalAgentFleetLogsView,
    LocalAgentFleetOutboxActionView,
    LocalAgentFleetUpdateView,
)
from apps.local_agents.models import LocalAgent
from apps.local_agents.releases import compare_release_versions
from apps.local_agents.views import LocalAgentDiagnosticsView, LocalAgentLogsView, LocalAgentUpdateNowView
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import Restaurant
from apps.users.models import Permission, Role, User
from apps.users.services import AdminAuthService


class _ManifestResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@override_settings(LOCAL_AGENT_RELEASE_MANIFEST_URL='https://updates.example/release.json')
class LocalAgentReleaseTests(APITestCase):
    def setUp(self):
        restaurant = Restaurant.objects.create(name='Release Restaurant')
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=restaurant)
        self.manifest = {
            'schemaVersion': 1,
            'version': '0.6.0',
            'platform': 'windows',
            'architecture': 'amd64',
            'downloadUrl': 'https://updates.example/CafePostcodeLocalAgent-0.6.0.exe',
            'sha256': 'a' * 64,
            'signature': base64.b64encode(b'x' * 64).decode(),
            'size': 123456,
            'mandatory': False,
        }

    def test_latest_release_requires_agent_token(self):
        response = self.client.get('/api/v1/local-agent/releases/latest/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('apps.local_agents.releases.urlopen')
    def test_latest_release_returns_validated_manifest(self, mocked_urlopen):
        mocked_urlopen.return_value = _ManifestResponse(json.dumps(self.manifest).encode())
        response = self.client.get(
            '/api/v1/local-agent/releases/latest/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['version'], '0.6.0')

    @patch('apps.local_agents.releases.urlopen')
    def test_latest_release_rejects_invalid_signature(self, mocked_urlopen):
        self.manifest['signature'] = base64.b64encode(b'short').decode()
        mocked_urlopen.return_value = _ManifestResponse(json.dumps(self.manifest).encode())
        response = self.client.get(
            '/api/v1/local-agent/releases/latest/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @override_settings(LOCAL_AGENT_RELEASE_MANIFEST_URL='')
    def test_latest_release_can_be_disabled(self):
        response = self.client.get(
            '/api/v1/local-agent/releases/latest/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_release_version_comparison_handles_prerelease(self):
        self.assertGreater(compare_release_versions('0.6.1', '0.6.0'), 0)
        self.assertGreater(compare_release_versions('0.6.1', '0.6.1-rc.1'), 0)
        self.assertEqual(compare_release_versions('v0.6.1', '0.6.1'), 0)


class _SuccessfulAgentCommandService:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs['command_type'] == 'system.status':
            return {
                'agent': {'online': True, 'version': '0.6.0'},
                'backend': {'online': True, 'offlineMode': False},
                'sync': {'ready': True, 'pendingOutbox': 0, 'failedOutbox': 0, 'schemaVersion': 1},
                'fiscal': {'configured': True, 'online': True, 'state': 'online'},
                'marta': {'configured': False, 'online': False, 'state': 'not_configured'},
                'printer': {'configured': True, 'online': True, 'state': 'online'},
                'alerts': [],
            }
        if kwargs['command_type'] == 'agent.logs':
            return {
                'available': True,
                'lines': ['normal log', 'Authorization: Bearer cpa_super-secret'],
            }
        return {'accepted': True, 'currentVersion': '0.6.0'}


class LocalAgentAdminMonitoringTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Admin Agent Restaurant')
        self.agent, _token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name='Cashier PC',
            version='0.6.0',
        )
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.capabilities = [
            'system_health',
            'auto_update',
            'context_refresh',
            'remote_restart',
            'remote_repair',
            'remote_logs',
            'outbox_management',
        ]
        self.agent.save(update_fields=['status', 'last_seen_at', 'capabilities', 'updated_at'])
        self.admin = User.objects.create_superuser(
            username='agent-monitor-admin',
            password='Strong-Agent-Monitor-123!',
            full_name='Agent Monitor Admin',
        )
        self.authenticate_admin()
        self.headers = {'HTTP_X_ADMIN_RESTAURANT_ID': str(self.restaurant.id)}

    def authenticate_admin(self, *, recent_mfa=True):
        verified_at = timezone.now() if recent_mfa else timezone.now() - timedelta(minutes=16)
        request = APIRequestFactory().post(
            '/',
            HTTP_ORIGIN='https://admin.cafe-postcode.uz',
            REMOTE_ADDR='192.0.2.44',
        )
        bundle = AdminAuthService().issue_credentials(
            user=self.admin,
            request=request,
            mfa_verified_at=verified_at,
        )
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {bundle.access_token}')
        return bundle

    @patch('apps.local_agents.views.agent_update_status')
    def test_admin_status_includes_version_and_pending_update(self, update_status):
        update_status.return_value = {
            'status': 'pending',
            'currentVersion': '0.6.0',
            'latestVersion': '0.6.1',
            'mandatory': False,
            'detail': '',
        }
        response = self.client.get('/api/v1/local-agent/status/', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['agent']['online'])
        self.assertEqual(response.data['agent']['version'], '0.6.0')
        self.assertEqual(response.data['update']['status'], 'pending')

    def test_admin_can_open_agent_diagnostics(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentDiagnosticsView, 'command_service_class', return_value=service):
            response = self.client.get('/api/v1/local-agent/diagnostics/', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['status']['backend']['online'])
        self.assertEqual(service.calls[0]['command_type'], 'system.status')

    def test_admin_can_request_immediate_update(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentUpdateNowView, 'command_service_class', return_value=service):
            response = self.client.post('/api/v1/local-agent/update-now/', {}, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['result']['accepted'])
        self.assertEqual(service.calls[0]['command_type'], 'agent.update_now')

    @override_settings(ADMIN_MFA_REQUIRED=True)
    def test_immediate_update_requires_recent_mfa_when_rollback_flag_is_enabled(self):
        self.authenticate_admin(recent_mfa=False)
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentUpdateNowView, 'command_service_class', return_value=service):
            response = self.client.post('/api/v1/local-agent/update-now/', {}, format='json', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertEqual(response.data['code'], 'mfa_step_up_required')
        self.assertEqual(service.calls, [])

    def test_admin_can_read_sanitized_agent_logs(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentLogsView, 'command_service_class', return_value=service):
            response = self.client.get('/api/v1/local-agent/logs/', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['lines'][0], 'normal log')
        self.assertNotIn('cpa_super-secret', response.data['lines'][1])
        self.assertIn('[REDACTED]', response.data['lines'][1])

    def test_restaurant_agent_logs_require_integration_view_permission(self):
        permission = Permission.objects.get(code='integration_configs.view')
        allowed_role = Role.objects.create(
            code='agent-logs-allowed',
            name='Agent logs allowed',
            is_system=False,
        )
        allowed_role.permissions.add(permission)
        denied_role = Role.objects.create(
            code='agent-logs-denied',
            name='Agent logs denied',
            is_system=False,
        )
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.restaurant, is_active=True)
        entitlement.permissions.add(permission)
        entitlement.allowed_roles.add(allowed_role, denied_role)
        allowed_user = User.objects.create_user(
            username='agent-logs-allowed',
            password='Strong-Agent-Monitor-123!',
            full_name='Agent Logs Allowed',
            restaurant=self.restaurant,
            role=allowed_role,
            is_staff=True,
        )
        denied_user = User.objects.create_user(
            username='agent-logs-denied',
            password='Strong-Agent-Monitor-123!',
            full_name='Agent Logs Denied',
            restaurant=self.restaurant,
            role=denied_role,
            is_staff=True,
        )
        service = _SuccessfulAgentCommandService()

        with patch.object(LocalAgentLogsView, 'command_service_class', return_value=service):
            self.client.force_authenticate(allowed_user)
            allowed_response = self.client.get('/api/v1/local-agent/logs/', **self.headers)
            self.client.force_authenticate(denied_user)
            denied_response = self.client.get('/api/v1/local-agent/logs/', **self.headers)

        self.assertEqual(allowed_response.status_code, status.HTTP_200_OK, allowed_response.data)
        self.assertEqual(denied_response.status_code, status.HTTP_403_FORBIDDEN, denied_response.data)
        self.assertEqual(len(service.calls), 1)

    def test_superuser_can_list_all_local_agents(self):
        offline_restaurant = Restaurant.objects.create(name='Offline Restaurant')
        offline_agent, _token = LocalAgent.issue_for_restaurant(
            restaurant=offline_restaurant,
            name='Offline PC',
            version='0.5.0',
        )
        offline_agent.status = LocalAgent.Status.ONLINE
        offline_agent.last_seen_at = timezone.now() - timedelta(minutes=5)
        offline_agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        response = self.client.get('/api/v1/admin/local-agents/?ordering=restaurantName')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['total'], 2)
        agents = {item['restaurant_name']: item for item in response.data['data']}
        self.assertEqual(agents['Admin Agent Restaurant']['status'], 'online')
        self.assertEqual(agents['Offline Restaurant']['status'], 'offline')

    def test_local_agent_fleet_is_superuser_only(self):
        regular_user = User.objects.create_user(
            username='regular-agent-monitor',
            password='Strong-Agent-Monitor-123!',
            full_name='Regular Agent Monitor',
        )
        self.client.force_authenticate(regular_user)

        response = self.client.get('/api/v1/admin/local-agents/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    def test_product_owner_permission_does_not_bypass_superuser_fleet_guard(self):
        product_owner = User.objects.create_user(
            username='product-owner-agent-monitor',
            password='Strong-Agent-Monitor-123!',
            full_name='Product Owner Agent Monitor',
            role=Role.objects.get(code='product_owner'),
            is_staff=True,
        )
        self.assertIn('platform.product_owner.view', product_owner.permission_codes)
        self.client.force_authenticate(product_owner)

        response = self.client.get('/api/v1/admin/local-agents/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    def test_superuser_can_run_fleet_diagnostics(self):
        service = _SuccessfulAgentCommandService()
        update = {
            'status': 'pending',
            'currentVersion': '0.6.0',
            'latestVersion': '0.7.5',
            'mandatory': False,
            'detail': '',
        }
        with (
            patch.object(LocalAgentFleetDiagnosticsView, 'command_service_class', return_value=service),
            patch('apps.local_agents.admin_views.agent_update_status', return_value=update),
        ):
            response = self.client.get(f'/api/v1/admin/local-agents/{self.agent.id}/diagnostics/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['status']['backend']['online'])
        self.assertEqual(response.data['update']['latestVersion'], '0.7.5')
        self.assertEqual(service.calls[0]['command_type'], 'system.status')

    def test_superuser_can_request_fleet_agent_update(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentFleetUpdateView, 'command_service_class', return_value=service):
            response = self.client.post(f'/api/v1/admin/local-agents/{self.agent.id}/update-now/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['result']['accepted'])
        self.assertEqual(service.calls[0]['command_type'], 'agent.update_now')

    def test_superuser_can_read_sanitized_agent_logs(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentFleetLogsView, 'command_service_class', return_value=service):
            response = self.client.get(f'/api/v1/admin/local-agents/{self.agent.id}/logs/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['lines'][0], 'normal log')
        self.assertNotIn('cpa_super-secret', response.data['lines'][1])
        self.assertIn('[REDACTED]', response.data['lines'][1])

    def test_superuser_can_retry_and_resolve_actionable_outbox_operation(self):
        service = _SuccessfulAgentCommandService()
        url = f'/api/v1/admin/local-agents/{self.agent.id}/outbox/failed-payment/'
        with patch.object(LocalAgentFleetOutboxActionView, 'command_service_class', return_value=service):
            retried = self.client.post(
                url,
                {'action': 'retry', 'reason': 'Cashier corrected the payment amount.'},
                format='json',
            )
            resolved = self.client.post(
                url,
                {'action': 'resolve', 'reason': 'The order was already closed on the server.'},
                format='json',
            )

        self.assertEqual(retried.status_code, status.HTTP_200_OK, retried.data)
        self.assertEqual(resolved.status_code, status.HTTP_200_OK, resolved.data)
        self.assertEqual(
            [call['command_type'] for call in service.calls],
            ['agent.outbox.retry', 'agent.outbox.dismiss_failed'],
        )
        self.assertEqual(service.calls[0]['payload']['operationId'], 'failed-payment')
        self.assertEqual(service.calls[1]['payload']['reason'], 'The order was already closed on the server.')

    def test_outbox_retry_requires_reason_but_resolve_does_not(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentFleetOutboxActionView, 'command_service_class', return_value=service):
            retry_response = self.client.post(
                f'/api/v1/admin/local-agents/{self.agent.id}/outbox/failed-payment/',
                {'action': 'retry', 'reason': '  '},
                format='json',
            )
            resolve_response = self.client.post(
                f'/api/v1/admin/local-agents/{self.agent.id}/outbox/failed-payment/',
                {'action': 'resolve', 'reason': '  '},
                format='json',
            )

        self.assertEqual(retry_response.status_code, status.HTTP_400_BAD_REQUEST, retry_response.data)
        self.assertEqual(resolve_response.status_code, status.HTTP_200_OK, resolve_response.data)
        self.assertEqual(len(service.calls), 1)
        self.assertEqual(service.calls[0]['command_type'], 'agent.outbox.dismiss_failed')
        self.assertEqual(service.calls[0]['payload']['reason'], '')

    def test_superuser_can_run_bulk_agent_action(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentFleetBulkActionView, 'command_service_class', return_value=service):
            response = self.client.post(
                '/api/v1/admin/local-agents/bulk-action/',
                {'action': 'refresh_context', 'agentIds': [str(self.agent.id)]},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['succeeded'], 1)
        self.assertEqual(service.calls[0]['command_type'], 'agent.refresh_context')

    def test_superuser_can_repair_agent_autostart_without_shell_payload(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentFleetBulkActionView, 'command_service_class', return_value=service):
            response = self.client.post(
                '/api/v1/admin/local-agents/bulk-action/',
                {'action': 'repair_autostart', 'agentIds': [str(self.agent.id)]},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['succeeded'], 1)
        self.assertEqual(service.calls[0]['command_type'], 'agent.repair_autostart')
        self.assertEqual(service.calls[0]['payload'], {})
