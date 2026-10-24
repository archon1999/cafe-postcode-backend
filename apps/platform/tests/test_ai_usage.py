import json
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.catalog_assistant.ai import CatalogAIUnavailable, extract_menu
from apps.inventory.ai import InventoryAIUnavailable, analyze_inventory
from apps.inventory.ai_documents import _read_model
from apps.platform.models import AIUsageLog, BusinessPartner, RestaurantEntitlement
from apps.platform.services.ai_usage import audit_ai_usage, estimated_cost, token_usage
from apps.restaurants.models import Restaurant
from apps.restaurants.services.service_fee_ai import generate_formula_draft
from apps.users.models import Permission, Role, User

PRICES = {'test-model': {'input': '2', 'cached_input': '0.5', 'output': '4'}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'ai-usage-tests'}}


def provider_result(output=None, **overrides):
    return {'id': 'resp_test123', 'model': 'test-model', 'status': 'completed',
            'usage': {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 200}, 'output_tokens': 100, 'total_tokens': 1100},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(output or {})}]}], **overrides}


def provider_response(result, status=200):
    return httpx.Response(status, json=result, headers={'x-request-id': 'req_test123'},
                          request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))


@override_settings(AI_USAGE_PRICING_USD_PER_MILLION=PRICES, CACHES=CACHES)
class AIUsageAccountingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partner = BusinessPartner.objects.create(inn='ai-audit-fixture', company_name='Fixture partner')
        cls.restaurant = Restaurant.objects.create(name='Fixture branch', business_partner=cls.partner)
        cls.user = User.objects.create_user(username='ai-audit-user', full_name='Fixture operator')

    def setUp(self):
        cache.clear()

    def audit(self, result, **kwargs):
        with audit_ai_usage('catalog_menu', 'test-model', restaurant=self.restaurant, user=self.user) as usage:
            usage.observe_http(provider_response(result))
            usage.observe_result(result)
        return AIUsageLog.objects.latest('created_at')

    def test_counts_cached_tokens_as_subset_and_prices_the_remainder_once(self):
        row = self.audit(provider_result())
        self.assertEqual((row.input_tokens, row.cached_input_tokens, row.output_tokens, row.total_tokens), (1000, 200, 100, 1100))
        self.assertEqual(row.estimated_cost_usd, Decimal('0.0021'))
        self.assertEqual({key: row.pricing[key] for key in PRICES['test-model']}, PRICES['test-model'])
        self.assertEqual(row.pricing['source'], 'operator_override')
        self.assertEqual(row.restaurant_id, self.restaurant.pk)
        self.assertEqual(row.business_partner_id, self.partner.pk)
        self.assertEqual(row.user_id, self.user.pk)
        self.assertEqual(row.request_id, 'req_test123')
        self.assertEqual(row.status, 'success')

    def test_unknown_model_or_missing_usage_remains_unpriced_not_fake_zero(self):
        first = self.audit(provider_result(model='unpriced-model'))
        self.assertIsNone(first.estimated_cost_usd)
        second = self.audit(provider_result(usage=None))
        self.assertIsNone(second.total_tokens)
        self.assertIsNone(second.input_tokens)
        self.assertIsNone(second.estimated_cost_usd)

    def test_explicit_zero_is_valid_and_invalid_token_values_are_not_coerced(self):
        usage = token_usage({'usage': {'input_tokens': 0, 'output_tokens': 0, 'input_tokens_details': {'cached_tokens': 0}, 'total_tokens': 0}})
        self.assertEqual(estimated_cost('test-model', usage)[0], Decimal('0'))
        usage = token_usage({'usage': {'input_tokens': True, 'output_tokens': -1, 'total_tokens': '50'}})
        self.assertIsNone(usage['input_tokens'])
        self.assertIsNone(usage['output_tokens'])
        self.assertIsNone(usage['total_tokens'])
        malformed = token_usage({'usage': {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 999, 'input_tokens_details': {'cached_tokens': 101}}})
        self.assertIsNone(malformed['cached_input_tokens'])
        self.assertIsNone(malformed['total_tokens'])

    def test_missing_cache_split_cannot_guess_a_discounted_cost(self):
        usage = token_usage({'usage': {'input_tokens': 100, 'output_tokens': 10}})
        self.assertIsNone(estimated_cost('test-model', usage)[0])
        self.assertEqual(usage['total_tokens'], 110)

    def test_incomplete_output_keeps_provider_usage_and_never_stores_error_content(self):
        with self.assertRaises(CatalogAIUnavailable):
            with audit_ai_usage('catalog_menu', 'test-model', restaurant=self.restaurant, user=self.user) as usage:
                usage.observe_result(provider_result(status='incomplete'))
                raise CatalogAIUnavailable('PRIVATE_PROMPT source upload sk-secret')
        row = AIUsageLog.objects.get()
        self.assertEqual(row.status, 'error')
        self.assertEqual(row.error_code, 'provider_incomplete')
        self.assertEqual(row.total_tokens, 1100)
        self.assertEqual(row.estimated_cost_usd, Decimal('0.0021'))
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(row.__dict__, default=str))
        self.assertNotIn('sk-secret', json.dumps(row.__dict__, default=str))

    def test_http_failure_retains_supplied_usage_without_provider_error_body(self):
        response = provider_response(provider_result(error={'message': 'PRIVATE_PROMPT sk-secret'}), status=429)
        with self.assertRaises(httpx.HTTPStatusError):
            with audit_ai_usage('inventory_analysis', 'test-model', restaurant=self.restaurant) as usage:
                usage.observe_http(response)
                response.raise_for_status()
        row = AIUsageLog.objects.get()
        self.assertEqual(row.error_code, 'provider_http_429')
        self.assertEqual(row.total_tokens, 1100)
        self.assertNotIn('PRIVATE_PROMPT', row.error_summary)

    def test_translated_timeout_keeps_safe_classification(self):
        with self.assertRaises(InventoryAIUnavailable):
            with audit_ai_usage('inventory_analysis', 'test-model', restaurant=self.restaurant):
                try:
                    raise httpx.ReadTimeout('PRIVATE_PROMPT sk-secret')
                except httpx.HTTPError:
                    raise InventoryAIUnavailable() from None
        row = AIUsageLog.objects.get()
        self.assertEqual(row.error_code, 'provider_timeout')
        self.assertIsNone(row.estimated_cost_usd)
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(row.__dict__, default=str))

    @patch('apps.platform.services.ai_usage._persist_usage', side_effect=DatabaseError('PRIVATE_PROMPT'))
    def test_audit_failure_does_not_mask_business_success_or_log_sensitive_error(self, persist):
        with self.assertLogs('apps.platform.services.ai_usage', level='WARNING') as messages:
            with audit_ai_usage('catalog_menu', 'test-model'):
                pass
        self.assertNotIn('PRIVATE_PROMPT', '\n'.join(messages.output))
        self.assertTrue(persist.called)
        self.assertEqual(AIUsageLog.objects.count(), 0)

    @patch('apps.platform.services.ai_usage._persist_usage', side_effect=DatabaseError('PRIVATE_PROMPT'))
    def test_audit_failure_does_not_hide_original_business_error(self, persist):
        with self.assertLogs('apps.platform.services.ai_usage', level='WARNING'):
            with self.assertRaisesRegex(ValueError, 'original'):
                with audit_ai_usage('catalog_menu', 'test-model'):
                    raise ValueError('original')

    @patch('apps.catalog_assistant.ai.ai_configuration', return_value=('fixture-key', 'test-model'))
    @patch('apps.catalog_assistant.ai.ai_proxy_url', return_value=None)
    @patch('apps.catalog_assistant.ai.httpx.Client')
    def test_catalog_actual_call_site_records_metadata_only(self, client_type, *_):
        output = {'rows': [{'name': 'Choy', 'name_ru': '', 'category_name': '', 'price': 5000, 'sale_unit': 'piece', 'description': '', 'evidence': 'PRIVATE_SOURCE', 'warning': ''}]}
        client_type.return_value.__enter__.return_value.post.return_value = provider_response(provider_result(output))
        extract_menu([{'type': 'input_text', 'text': 'PRIVATE_SOURCE'}], [], restaurant=self.restaurant, user=self.user)
        row = AIUsageLog.objects.get()
        self.assertEqual(row.feature, 'catalog_menu')
        self.assertEqual(row.user_id, self.user.pk)
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(row.__dict__, default=str))

    @patch('apps.inventory.ai.ai_configuration', return_value=('fixture-key', 'test-model'))
    @patch('apps.inventory.ai.ai_proxy_url', return_value=None)
    @patch('apps.inventory.reports.insights', return_value={'items': [{'id': 'stock-1', 'severity': 'critical'}]})
    @patch('apps.inventory.ai.httpx.Client')
    def test_inventory_cached_response_does_not_duplicate_paid_usage(self, client_type, *_):
        output = {'summary': 'Stock check', 'recommendations': [{'title': 'Count stock', 'detail': 'Check source', 'evidenceIds': ['stock-1']}]}
        client_type.return_value.__enter__.return_value.post.return_value = provider_response(provider_result(output))
        analyze_inventory(self.restaurant, user=self.user)
        analyze_inventory(self.restaurant, user=self.user)
        self.assertEqual(AIUsageLog.objects.count(), 1)
        self.assertEqual(AIUsageLog.objects.get().feature, 'inventory_analysis')

    @patch('apps.inventory.ai_documents.ai_configuration', return_value=('fixture-key', 'test-model'))
    @patch('apps.inventory.ai_documents.ai_proxy_url', return_value=None)
    @patch('apps.inventory.ai_documents.httpx.Client')
    def test_inventory_document_provider_call_is_audited(self, client_type, *_):
        output = {'kind': None, 'kindEvidence': '', 'kindSource': 'text', 'summary': '', 'rows': [], 'warnings': []}
        client_type.return_value.__enter__.return_value.post.return_value = provider_response(provider_result(output))
        _read_model([{'type': 'input_text', 'text': 'PRIVATE_SOURCE'}], [], 'auto', 'uz', restaurant=self.restaurant, user=self.user)
        self.assertEqual(AIUsageLog.objects.get().feature, 'inventory_document')

    @patch('apps.restaurants.services.service_fee_ai.ai_configuration', return_value=('fixture-key', 'test-model'))
    @patch('apps.restaurants.services.service_fee_ai.ai_proxy_url', return_value=None)
    @patch('apps.restaurants.services.service_fee_ai.httpx.Client')
    def test_formula_provider_call_is_audited_without_formula_source(self, client_type, *_):
        output = {'name': 'Draft', 'source': '', 'parameters': [], 'explanation': 'Need details', 'questions': ['Which rate?']}
        client_type.return_value.__enter__.return_value.post.return_value = provider_response(provider_result(output))
        generate_formula_draft('PRIVATE_SOURCE', restaurant=self.restaurant, user=self.user)
        row = AIUsageLog.objects.get()
        self.assertEqual(row.feature, 'service_fee_formula')
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(row.__dict__, default=str))


@override_settings(AI_USAGE_PRICING_USD_PER_MILLION={})
class AIUsageApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username='ai-admin', full_name='Super admin', is_staff=True, is_superuser=True)
        cls.staff = User.objects.create_user(username='ai-staff', full_name='Platform staff', is_staff=True, role=Role.objects.get(code='product_owner'))
        cls.partner1 = BusinessPartner.objects.create(inn='ai-partner-one', company_name='Partner one')
        cls.partner2 = BusinessPartner.objects.create(inn='ai-partner-two', company_name='Partner two')
        cls.branch1 = Restaurant.objects.create(name='Alpha branch', business_partner=cls.partner1)
        cls.branch2 = Restaurant.objects.create(name='Beta branch', business_partner=cls.partner2)
        cls.tenant = User.objects.create_user(username='ai-tenant', full_name='Tenant staff', restaurant=cls.branch1, is_staff=True)
        cls.partner_user = User.objects.create_user(username='ai-partner', full_name='Partner owner', business_partner=cls.partner1)
        cls.first = cls.event(cls.branch1, 'catalog_menu', 'model-a', 'success', 100, 10, Decimal('0.001'), '2026-10-24T20:30:00+00:00')
        cls.event(cls.branch2, 'inventory_analysis', 'model-b', 'error', None, None, None, '2026-10-24T10:00:00+00:00')
        cls.event(cls.branch1, 'service_fee_formula', 'model-a', 'success', 50, 5, None, '2026-10-25T00:00:00+00:00')
        cls.event(cls.branch2, 'inventory_document', 'outside-range', 'success', 999, 1, None, '2026-10-26T00:00:00+00:00')

    @classmethod
    def event(cls, restaurant, feature, model, status, incoming, outgoing, cost, at):
        row = AIUsageLog.objects.create(restaurant=restaurant, business_partner=restaurant.business_partner, user=cls.admin,
            restaurant_name=restaurant.name, business_partner_name=restaurant.business_partner.company_name, user_name='Super admin',
            feature=feature, model=model, status=status, input_tokens=incoming, output_tokens=outgoing,
            cached_input_tokens=20 if cost is not None else 0 if incoming is not None else None,
            total_tokens=incoming + outgoing if incoming is not None else None, estimated_cost_usd=cost,
            duration_ms=200, request_id=f'req_{feature}', error_code='provider_timeout' if status == 'error' else '', error_summary='Safe generic message' if status == 'error' else '')
        AIUsageLog.objects.filter(pk=row.pk).update(created_at=datetime.fromisoformat(at))
        return row

    def setUp(self):
        self.client.force_authenticate(self.admin)
        self.range = {'from': '2026-10-24T00:00:00Z', 'to': '2026-10-26T00:00:00Z'}

    def get(self, suffix='summary', **filters):
        return self.client.get(f'/api/v1/admin/ai-usage/{suffix}/', {**self.range, **filters})

    def test_only_real_superadmins_can_read_usage(self):
        for user in (None, self.staff, self.tenant, self.partner_user):
            with self.subTest(user=getattr(user, 'username', None)):
                self.client.force_authenticate(user)
                self.assertIn(self.get().status_code, (401, 403))
                self.assertIn(self.get('requests').status_code, (401, 403))

    def test_explicit_usage_permission_cannot_bypass_superadmin_guard(self):
        permission = Permission.objects.get(code='platform.ai_usage.view')
        self.partner1.status = BusinessPartner.Status.ACTIVE
        self.partner1.save(update_fields=['status'])
        self.branch1.is_active = True
        self.branch1.save(update_fields=['is_active'])
        entitlement = RestaurantEntitlement.objects.create(restaurant=self.branch1, is_active=True)
        entitlement.permissions.add(permission)
        for user, role_code in ((self.staff, 'product_owner'), (self.partner_user, 'business_partner'),
                                (self.tenant, 'restaurant_admin')):
            with self.subTest(role=role_code):
                role = Role.objects.get(code=role_code)
                role.permissions.add(permission)
                user.role = role
                user.save(update_fields=['role'])
                self.assertIn(permission.code, user.permission_codes)
                self.client.force_authenticate(user)
                self.assertEqual(self.get().status_code, 403)
                self.assertEqual(self.get('requests').status_code, 403)

    def test_summary_known_subtotals_status_missing_usage_and_tashkent_trend(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.data)
        totals = response.data['totals']
        self.assertEqual(totals['requestCount'], 3)
        self.assertEqual((totals['successCount'], totals['errorCount']), (2, 1))
        self.assertEqual((totals['inputTokens'], totals['cachedInputTokens'], totals['outputTokens'], totals['totalTokens']), (150, 20, 15, 165))
        self.assertEqual(Decimal(totals['estimatedCostUsd']), Decimal('0.001'))
        self.assertEqual((totals['pricedRequestCount'], totals['unpricedRequestCount'], totals['missingUsageCount']), (1, 2, 1))
        self.assertEqual([(row['date'], row['requestCount']) for row in response.data['trend']], [('2026-10-24', 1), ('2026-10-25', 2), ('2026-10-26', 0)])
        self.assertEqual(len(response.data['branches']), 2)
        self.assertIsNotNone(response.data['trackingStartedAt'])

    def test_explicit_partner_and_branch_filters_intersect_without_ambient_header_scope(self):
        all_rows = self.client.get('/api/v1/admin/ai-usage/summary/', self.range, HTTP_X_ADMIN_RESTAURANT_ID=str(self.branch1.pk))
        self.assertEqual(all_rows.data['totals']['requestCount'], 3)
        self.assertEqual(self.get(business_partner_id=str(self.partner1.pk)).data['totals']['requestCount'], 2)
        self.assertEqual(self.get(restaurant_id=str(self.branch2.pk)).data['totals']['requestCount'], 1)
        mismatch = self.get(restaurant_id=str(self.branch2.pk), business_partner_id=str(self.partner1.pk))
        self.assertEqual(mismatch.data['totals']['requestCount'], 0)

    def test_feature_model_status_and_search_are_server_filters_and_options_keep_alternatives(self):
        self.assertEqual(self.get(feature='catalog_menu').data['totals']['requestCount'], 1)
        result = self.get(model='model-b', status='error', search='Beta')
        self.assertEqual(result.data['totals']['requestCount'], 1)
        self.assertIsNone(result.data['totals']['estimatedCostUsd'])
        self.assertEqual(result.data['filterOptions']['models'], ['model-a', 'model-b'])
        self.assertEqual(self.get(search='no match').data['totals']['requestCount'], 0)
        self.assertEqual(self.get(search='provider_timeout').data['totals']['errorCount'], 1)

    def test_paginated_ordered_metadata_contains_no_payload_or_pricing_secrets(self):
        response = self.get('requests', page_size=1, page=2, ordering='total_tokens')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(response.data['pageSize'], 1)
        self.assertEqual(response.data['results'][0]['totalTokens'], 110)
        record = response.data['results'][0]
        self.assertEqual(record['restaurantName'], 'Alpha branch')
        for forbidden in ('prompt', 'input', 'output', 'uploadedContent', 'apiKey', 'pricing'):
            self.assertNotIn(forbidden, record)
        self.assertEqual(self.get('requests', page=999).data['results'], [])

    def test_invalid_or_excessive_filters_are_rejected_and_endpoints_are_read_only(self):
        for values in ({'restaurant_id': 'bad'}, {'business_partner_id': 'bad'}, {'page_size': 101}, {'page': 0},
                       {'ordering': 'user__password'}, {'status': 'all'}, {'feature': 'unknown'}, {'unknown': 'x'},
                       {'from': '2026-10-24T00:00:00'}, {'from': '2026-10-26T00:00:00Z'},
                       {'from': '2020-01-01T00:00:00Z'}):
            with self.subTest(values=values):
                self.assertEqual(self.get('requests', **values).status_code, 400)
        before = AIUsageLog.objects.count()
        self.assertEqual(self.client.post('/api/v1/admin/ai-usage/requests/', {}, format='json').status_code, 405)
        self.assertEqual(AIUsageLog.objects.count(), before)

    def test_group_rows_are_bounded_and_empty_range_has_known_zero_requests(self):
        for index in range(101):
            AIUsageLog.objects.create(feature='catalog_menu', model=f'group-{index}', status='success')
        response = self.client.get('/api/v1/admin/ai-usage/summary/')
        self.assertLessEqual(len(response.data['models']), 100)
        self.assertTrue(response.data['groupsTruncated'])
        empty = self.get(**{'from': '2025-01-01T00:00:00Z', 'to': '2025-01-02T00:00:00Z'})
        self.assertEqual(empty.data['totals']['requestCount'], 0)
        self.assertEqual(Decimal(empty.data['totals']['estimatedCostUsd']), 0)
