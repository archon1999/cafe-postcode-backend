import base64
import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.local_agents.models import LocalAgent
from apps.local_agents.releases import agent_update_status
from apps.local_agents.tests_support import bind_agent_client
from apps.restaurants.models import Restaurant


STABLE_URL = 'https://updates.example/downloads/local-agent-release.json'
CANARY_URL = 'https://updates.example/downloads/canary/2.0.0-rc.1/local-agent-release.json'


@override_settings(LOCAL_AGENT_RELEASE_MANIFEST_URL=STABLE_URL,
                   LOCAL_AGENT_CANARY_RELEASE_MANIFEST_URL=CANARY_URL)
class LocalAgentCanaryReleaseTests(APITestCase):
    def setUp(self):
        self.canary, self.canary_token = LocalAgent.issue_for_restaurant(
            restaurant=Restaurant.objects.create(name='Canary acceptance'))
        self.stable, self.stable_token = LocalAgent.issue_for_restaurant(
            restaurant=Restaurant.objects.create(name='Stable branch'))
        self.canary.version = self.stable.version = '1.2.4'
        self.stable_client = APIClient()
        bind_agent_client(self.client, self.canary, self.canary_token)
        bind_agent_client(self.stable_client, self.stable, self.stable_token)
        settings = override_settings(LOCAL_AGENT_CANARY_RESTAURANT_IDS=[str(self.canary.restaurant_id)])
        settings.enable()
        self.addCleanup(settings.disable)

    @staticmethod
    def manifest(version):
        return {'schemaVersion': 1, 'version': version, 'platform': 'windows', 'architecture': 'amd64',
                'downloadUrl': 'https://updates.example/agent.exe', 'sha256': 'a'*64,
                'signature': base64.b64encode(b'x'*64).decode(), 'size': 17000000, 'mandatory': False}

    def fetch(self, request, **kwargs):
        self.assertEqual(kwargs['timeout'], 5)
        self.assertIn(request.full_url, [STABLE_URL, CANARY_URL])
        version = '2.0.0-rc.1' if request.full_url == CANARY_URL else '1.2.4'
        return BytesIO(json.dumps(self.manifest(version)).encode())

    def latest(self, canary=True, query=''):
        client, token = (self.client, self.canary_token) if canary else (self.stable_client, self.stable_token)
        return client.get('/api/v1/local-agent/releases/latest/' + query, HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('apps.local_agents.releases.urlopen')
    def test_only_authenticated_allowlisted_restaurant_receives_canary(self, fetch):
        fetch.side_effect = self.fetch
        response = self.latest()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['version'], '2.0.0-rc.1')
        other = self.latest(canary=False, query=f'?restaurantId={self.canary.restaurant_id}&channel=canary')
        self.assertEqual(other.status_code, 200, other.data)
        self.assertEqual(other.data['version'], '1.2.4')
        self.assertEqual([call.args[0].full_url for call in fetch.call_args_list], [CANARY_URL, STABLE_URL])

    @patch('apps.local_agents.releases.urlopen')
    def test_admin_status_uses_the_same_restaurant_channel(self, fetch):
        fetch.side_effect = self.fetch
        self.assertEqual(agent_update_status(self.canary)['latestVersion'], '2.0.0-rc.1')
        stable = agent_update_status(self.stable)
        self.assertEqual(stable['latestVersion'], '1.2.4')
        self.assertEqual(stable['status'], 'up_to_date')

    @override_settings(LOCAL_AGENT_CANARY_RESTAURANT_IDS=[])
    @patch('apps.local_agents.releases.urlopen')
    def test_no_allowlist_means_stable_even_with_canary_url_configured(self, fetch):
        fetch.side_effect = self.fetch
        self.assertEqual(self.latest().data['version'], '1.2.4')
        self.assertEqual(fetch.call_args.args[0].full_url, STABLE_URL)

    @patch('apps.local_agents.releases.urlopen')
    def test_canary_failure_does_not_fall_back_or_affect_other_branches(self, fetch):
        def fail_canary(request, **kwargs):
            if request.full_url == CANARY_URL:
                raise URLError('Canary temporarily unavailable')
            return self.fetch(request, **kwargs)
        fetch.side_effect = fail_canary
        self.assertEqual(self.latest().status_code, 503)
        self.assertEqual(self.latest(canary=False).data['version'], '1.2.4')
        self.assertEqual([call.args[0].full_url for call in fetch.call_args_list], [CANARY_URL, STABLE_URL])

    @patch('apps.local_agents.releases.urlopen')
    def test_invalid_selected_url_is_rejected_before_network_access(self, fetch):
        for url in ['', 'http://updates.example/test.json', 'https://user:secret@updates.example/test.json',
                    'https://updates.example/test.json#fragment']:
            with self.subTest(url=url), override_settings(LOCAL_AGENT_CANARY_RELEASE_MANIFEST_URL=url):
                self.assertEqual(self.latest().status_code, 503)
        fetch.assert_not_called()

    @patch('apps.local_agents.releases.urlopen')
    def test_unsigned_caller_cannot_select_any_release(self, fetch):
        response = APIClient().get('/api/v1/local-agent/releases/latest/?channel=canary')
        self.assertEqual(response.status_code, 401)
        fetch.assert_not_called()
