from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.local_agents.admin_views import LocalAgentLatestStableReleaseView
from apps.local_agents.releases import latest_stable_release_summary


@override_settings(
    LOCAL_AGENT_RELEASE_MANIFEST_URL='https://updates.example/stable.json',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LatestStableReleaseSummaryTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    @patch('apps.local_agents.releases.fetch_release_manifest')
    def test_reads_and_caches_published_version(self, fetch):
        fetch.return_value = {'version': '2.4.5', 'downloadUrl': 'private-download-url'}
        expected = {'status': 'available', 'version': '2.4.5'}
        self.assertEqual(latest_stable_release_summary(), expected)
        self.assertEqual(latest_stable_release_summary(), expected)
        fetch.assert_called_once_with()

    @patch('apps.local_agents.releases.fetch_release_manifest', side_effect=URLError('network'))
    def test_unavailable_release_is_not_reported_as_an_installed_version(self, fetch):
        self.assertEqual(latest_stable_release_summary(), {'status': 'unavailable', 'version': None})
        latest_stable_release_summary()
        fetch.assert_called_once()

    @override_settings(LOCAL_AGENT_RELEASE_MANIFEST_URL='')
    @patch('apps.local_agents.releases.fetch_release_manifest')
    def test_disabled_release_does_not_make_network_requests(self, fetch):
        self.assertEqual(latest_stable_release_summary(), {'status': 'disabled', 'version': None})
        fetch.assert_not_called()

    @patch('apps.local_agents.admin_views.latest_stable_release_summary')
    def test_only_superadmin_can_read_release_summary(self, summary):
        factory = APIRequestFactory()
        for allowed in (False, True):
            request = factory.get('/api/v1/admin/local-agents/latest-release/')
            force_authenticate(request, user=SimpleNamespace(is_authenticated=True, is_superuser=allowed))
            summary.return_value = {'status': 'available', 'version': '2.4.5'}
            response = LocalAgentLatestStableReleaseView.as_view()(request)
            self.assertEqual(response.status_code, 200 if allowed else 403)
        summary.assert_called_once()
