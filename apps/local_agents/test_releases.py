import base64
import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.local_agents.admin_views import (
    LocalAgentFleetBulkActionView,
    LocalAgentFleetDiagnosticsView,
    LocalAgentFleetLogsView,
    LocalAgentFleetUpdateView,
)
from apps.local_agents.models import LocalAgent
from apps.local_agents.releases import compare_release_versions
from apps.local_agents.views import LocalAgentDiagnosticsView, LocalAgentLogsView, LocalAgentUpdateNowView
from apps.restaurants.models import Restaurant
from apps.users.models import User


class _ManifestResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@override_settings(LOCAL_AGENT_RELEASE_MANIFEST_URL='https://updates.example/release.json')
class LocalAgentReleaseTests(APITestCase):
    def setUp(self):
        restaurant = Restaurant.objects.create(name='Release Restaurant', auth_code='REL123')
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
        self.restaurant = Restaurant.objects.create(name='Admin Agent Restaurant', auth_code='ADM123')
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
            'remote_logs',
        ]
        self.agent.save(update_fields=['status', 'last_seen_at', 'capabilities', 'updated_at'])
        self.admin = User.objects.create_superuser(
            username='agent-monitor-admin',
            password='Strong-Agent-Monitor-123!',
            full_name='Agent Monitor Admin',
        )
        self.client.force_authenticate(self.admin)
        self.headers = {'HTTP_X_ADMIN_RESTAURANT_ID': str(self.restaurant.id)}

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

    def test_admin_can_read_sanitized_agent_logs(self):
        service = _SuccessfulAgentCommandService()
        with patch.object(LocalAgentLogsView, 'command_service_class', return_value=service):
            response = self.client.get('/api/v1/local-agent/logs/', **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['lines'][0], 'normal log')
        self.assertNotIn('cpa_super-secret', response.data['lines'][1])
        self.assertIn('[REDACTED]', response.data['lines'][1])

    def test_superuser_can_list_all_local_agents(self):
        offline_restaurant = Restaurant.objects.create(name='Offline Restaurant', auth_code='OFF123')
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
