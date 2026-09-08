import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.inventory.ai import InventoryAIUnavailable, ai_configuration, ai_proxy_url, analyze_inventory, validate_analysis


class InventoryAnalysisTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.facts = {'items': [{'id': 'shortage-1', 'title': 'Kartoshka kam', 'evidence': {'quantity': '20'}}]}
        self.analysis = {'summary': 'Qoldiqni tekshiring.', 'recommendations': [
            {'title': 'Qayta sanash', 'detail': 'Kartoshkani qayta torting.', 'evidenceIds': ['shortage-1']},
        ]}

    @override_settings(INVENTORY_AI_API_KEY='', INVENTORY_AI_MODEL='')
    @patch.dict('os.environ', {'INVENTORY_AI_API_KEY': 'test-key', 'INVENTORY_AI_MODEL': ''})
    def test_default_model_is_luna(self):
        self.assertEqual(ai_configuration(), ('test-key', 'gpt-5.6-luna'))

    @override_settings(INVENTORY_AI_PROXY_URL='')
    @patch.dict('os.environ', {'INVENTORY_AI_PROXY_URL': ''})
    def test_proxy_is_optional(self):
        self.assertIsNone(ai_proxy_url())

    @override_settings(INVENTORY_AI_PROXY_URL='')
    @patch.dict('os.environ', {'INVENTORY_AI_PROXY_URL': ' http://proxy.example:8000 '})
    def test_proxy_configuration_from_environment(self):
        self.assertEqual(ai_proxy_url(), 'http://proxy.example:8000')

    def test_unrecognized_evidence_is_rejected(self):
        self.analysis['recommendations'][0]['evidenceIds'] = ['invented-1']
        with self.assertRaises(InventoryAIUnavailable):
            validate_analysis(self.analysis, {'shortage-1'})

    @override_settings(INVENTORY_AI_API_KEY='test-not-a-real-key', INVENTORY_AI_MODEL='configured-test-model',
                       INVENTORY_AI_PROXY_URL='http://operator:private-password@proxy.example:8000')
    @patch('apps.inventory.reports.insights')
    @patch('apps.inventory.ai.httpx.Client')
    def test_grounded_response_is_read_only_and_cached_per_tenant(self, client_type, insights):
        insights.return_value = self.facts
        response = MagicMock()
        response.json.return_value = {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(self.analysis)}]},
        ]}
        client = client_type.return_value.__enter__.return_value
        client.post.return_value = response
        first = analyze_inventory(SimpleNamespace(pk='restaurant-a'))
        self.assertEqual(first['mode'], 'ai')
        self.assertEqual(first, analyze_inventory(SimpleNamespace(pk='restaurant-a')))
        self.assertEqual(client.post.call_count, 1)
        analyze_inventory(SimpleNamespace(pk='restaurant-b'))
        self.assertEqual(client.post.call_count, 2)
        body = client.post.call_args.kwargs['json']
        self.assertFalse(body['store'])
        self.assertNotIn('tools', body)
        self.assertEqual(body['model'], 'configured-test-model')
        self.assertEqual(body['reasoning'], {'effort': 'low'})
        self.assertEqual(client_type.call_args.kwargs['proxy'], 'http://operator:private-password@proxy.example:8000')
        self.assertNotIn('private-password', json.dumps(body))
        self.assertNotIn('private-password', json.dumps(first))

    @override_settings(INVENTORY_AI_API_KEY='test-not-a-real-key', INVENTORY_AI_MODEL='configured-test-model')
    @patch('apps.inventory.reports.insights')
    @patch('apps.inventory.ai.httpx.Client')
    def test_upstream_failure_does_not_leak_credentials(self, client_type, insights):
        insights.return_value = self.facts
        client_type.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError('secret-value')
        with self.assertRaises(InventoryAIUnavailable) as caught:
            analyze_inventory(SimpleNamespace(pk='restaurant-a'))
        self.assertNotIn('secret-value', str(caught.exception))

    @override_settings(INVENTORY_AI_API_KEY='private-key')
    @patch('apps.inventory.reports.insights')
    @patch('apps.inventory.ai.httpx.Client')
    def test_proxy_failure_does_not_leak_credentials(self, client_type, insights):
        insights.return_value = self.facts
        client_type.return_value.__enter__.return_value.post.side_effect = httpx.ProxyError(
            'http://operator:private-password@proxy.example:8000')
        with self.assertRaises(InventoryAIUnavailable) as caught:
            analyze_inventory(SimpleNamespace(pk='restaurant-a'))
        self.assertNotIn('private-password', str(caught.exception))
        self.assertNotIn('private-key', str(caught.exception))


class InventoryAnalysisAccessTests(TestCase):
    def setUp(self):
        from apps.restaurants.models import Restaurant
        from apps.users.models import Role, Permission, User
        from apps.platform.models import RestaurantEntitlement

        cache.clear()
        self.restaurant = Restaurant.objects.create(name='AI local test')
        self.other = Restaurant.objects.create(name='Other AI tenant')
        self.permissions = Permission.objects.filter(code__in=[
            'admin.inventory.view', 'admin.inventory.view_cost', 'admin.inventory.analyze'])
        self.role = Role.objects.create(code='inventory-ai-test', name='AI test')
        self.role.permissions.set(self.permissions)
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.restaurant, is_active=True, is_custom=True)
        entitlement.permissions.set(self.permissions)
        self.user = User.objects.create_user('inventory-ai-test', restaurant=self.restaurant, role=self.role, full_name='AI test')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.endpoint = '/api/v1/admin/inventory/insights/analyze/'

    @patch('apps.inventory.ai_views.analyze_inventory')
    def test_analysis_requires_every_permission_before_sending_data(self, analyze):
        from apps.users.models import User

        for denied in ['admin.inventory.view_cost', 'admin.inventory.analyze', 'admin.inventory.view']:
            self.role.permissions.set(self.permissions.exclude(code=denied))
            self.client.force_authenticate(User.objects.get(pk=self.user.pk))
            response = self.client.post(self.endpoint, {}, format='json')
            self.assertEqual(response.status_code, 403, response.data)
        analyze.assert_not_called()

    @patch('apps.inventory.ai_views.analyze_inventory')
    def test_analysis_scopes_warehouse_and_forwards_locale(self, analyze):
        from apps.inventory.services import default_warehouse

        foreign = default_warehouse(self.other)
        response = self.client.post(self.endpoint, {'warehouse': str(foreign.pk)}, format='json')
        self.assertEqual(response.status_code, 400)
        analyze.assert_not_called()
        analyze.return_value = {'mode': 'ai', 'summary': 'Dalil', 'recommendations': []}
        own = default_warehouse(self.restaurant)
        response = self.client.post(self.endpoint, {'warehouse': str(own.pk)}, format='json', HTTP_ACCEPT_LANGUAGE='ru')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(analyze.call_args.args, (self.restaurant, own, 'ru'))

    @patch('apps.inventory.ai.ai_configuration', return_value=('', ''))
    def test_unconfigured_provider_is_explicit_and_rules_remain_available(self, configuration):
        response = self.client.post(self.endpoint, {}, format='json')
        self.assertEqual(response.status_code, 503)
        rules = self.client.get('/api/v1/admin/inventory/insights/')
        self.assertEqual(rules.status_code, 200)
        self.assertEqual(rules.json()['mode'], 'rules')
        self.assertFalse(rules.json()['aiAvailable'])
