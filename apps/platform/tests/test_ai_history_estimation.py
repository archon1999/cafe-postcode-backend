import io
import json
import runpy
import sys
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from apps.catalog_assistant.ai import PROPERTIES
from apps.platform.models import AIUsageLog
from apps.platform.services.ai_history_estimation import (
    CONFIRMED_MODEL, ESTIMATION_METHOD, _text_tokens, estimate_draft_tokens, estimate_recovered_catalog_usage,
)
from apps.platform.services.ai_history_recovery import RecoveryEvidenceError, recover_catalog_usage
from apps.platform.tests.test_ai_history_recovery import CUTOFF, RecoveryFixture
from apps.users.models import User


@override_settings(AI_USAGE_PRICING_USD_PER_MILLION={})
class AIHistoryEstimationTests(RecoveryFixture, TestCase):
    def setUp(self):
        cutoff = patch('apps.platform.services.ai_history_recovery.historical_cutoff', return_value=CUTOFF)
        cutoff.start()
        self.addCleanup(cutoff.stop)
        cutoff = patch('apps.platform.services.ai_history_estimation.historical_cutoff', return_value=CUTOFF)
        cutoff.start()
        self.addCleanup(cutoff.stop)

    def recover(self, rows=None):
        draft = self.draft(CUTOFF - timedelta(days=1), rows=rows)
        recover_catalog_usage(apply=True, expected_count=AIUsageLog.objects.filter(source='catalog_draft').count() + 1)
        return draft

    def estimate(self, **kwargs):
        return estimate_recovered_catalog_usage(model=CONFIRMED_MODEL, **kwargs)

    def test_text_proxy_rounds_up_and_weights_unicode_without_external_calls(self):
        self.assertEqual([_text_tokens(text) for text in ('a', 'abcd', 'abcde', 'Ўзбекча')], [1, 1, 2, 4])

    def test_estimator_excludes_review_fields_and_deduplicates_source_excerpts(self):
        draft = self.recover(rows=[{'name': 'Choy', 'evidence': 'Choy 5000', 'price': 5000,
                                    'selected': True, 'mxik_code': '12345678901234567', 'category_id': 'private'}])
        original = estimate_draft_tokens(draft)
        draft.rows[0].update(selected=False, category_id='a' * 1000, mxik_code='9' * 1000, unexpected='x' * 1000)
        self.assertEqual(estimate_draft_tokens(draft), original)
        draft.rows.append(dict(draft.rows[0]))
        doubled = estimate_draft_tokens(draft)
        self.assertEqual(doubled[0]['input_tokens'], original[0]['input_tokens'])
        self.assertGreater(doubled[0]['output_tokens'], original[0]['output_tokens'])
        projected = {key: draft.rows[0].get(key, None if key == 'price' else 'piece' if key == 'sale_unit' else '') for key in PROPERTIES}
        self.assertEqual(original[3]['outputProxyBytes'], len(json.dumps({'rows': [projected]}, ensure_ascii=False,
            separators=(',', ':'), sort_keys=True).encode('utf-8')))

    def test_dry_run_projects_totals_without_changing_any_data(self):
        self.recover()
        before = list(AIUsageLog.objects.values())
        report = self.estimate(expected_count=1)
        self.assertEqual((report['willEstimate'], report['updated']), (1, 0))
        self.assertGreater(report['estimatedTotalTokens'], 0)
        self.assertGreater(Decimal(report['estimatedTotalCostUsd']), 0)
        self.assertEqual(list(AIUsageLog.objects.values()), before)

    def test_apply_retains_provenance_and_unknowns_and_does_not_copy_private_content(self):
        self.recover()
        original = AIUsageLog.objects.values().get()
        self.estimate(apply=True, expected_count=1)
        row = AIUsageLog.objects.get()
        self.assertEqual(row.model, CONFIRMED_MODEL)
        self.assertTrue(row.usage_is_estimated)
        self.assertEqual(row.input_tokens + row.output_tokens, row.total_tokens)
        self.assertIsNone(row.cached_input_tokens)
        self.assertIsNone(row.duration_ms)
        self.assertEqual(row.request_id, '')
        self.assertEqual(row.pricing['cached_input_assumption'], 0)
        self.assertEqual(row.evidence['usageEstimate']['modelBasis'], 'operator_confirmed')
        self.assertEqual(row.evidence['usageEstimate']['method'], ESTIMATION_METHOD)
        self.assertEqual(row.estimated_cost_usd,
            (Decimal(row.input_tokens) * Decimal('0.20') + Decimal(row.output_tokens) * Decimal('1.20')) / 1000000)
        for key in ('id', 'created_at', 'recovered_at', 'restaurant_id', 'business_partner_id', 'user_id'):
            self.assertEqual(getattr(row, key), original[key])
        serialized = json.dumps(row.__dict__, default=str)
        for private in ('PRIVATE_SOURCE', 'PRIVATE_UPLOAD', 'sk-private'):
            self.assertNotIn(private, serialized)

    def test_live_measurements_are_unchanged_and_estimates_freeze_on_repeat(self):
        draft = self.recover()
        live = AIUsageLog.objects.create(feature='catalog_menu', model='observed-model', status='success',
            input_tokens=20, output_tokens=10, cached_input_tokens=5, total_tokens=30, estimated_cost_usd=Decimal('0.001'))
        before_live = AIUsageLog.objects.values().get(pk=live.pk)
        self.estimate(apply=True, expected_count=1)
        before_recovered = AIUsageLog.objects.values().get(source='catalog_draft')
        draft.rows = [{'name': 'Edited much later'}]
        draft.save(update_fields=['rows'])
        with patch('apps.platform.services.ai_history_estimation.estimate_draft_tokens', side_effect=AssertionError('Must not recalculate')):
            report = self.estimate(apply=True, expected_count=1)
        self.assertEqual((report['willEstimate'], report['alreadyEstimated'], report['updated']), (0, 1, 0))
        self.assertEqual(AIUsageLog.objects.values().get(pk=live.pk), before_live)
        self.assertEqual(AIUsageLog.objects.values().get(source='catalog_draft'), before_recovered)

    def test_invalid_count_or_confirmation_or_preexisting_measurement_fails_without_mutation(self):
        self.recover()
        before = list(AIUsageLog.objects.values())
        for kwargs in ({'model': 'other'}, {'expected_count': 2}, {'apply': True}):
            with self.assertRaises(RecoveryEvidenceError):
                estimate_recovered_catalog_usage(**{'model': CONFIRMED_MODEL, **kwargs})
        self.assertEqual(list(AIUsageLog.objects.values()), before)
        AIUsageLog.objects.update(total_tokens=123)
        with self.assertRaises(RecoveryEvidenceError):
            self.estimate(apply=True, expected_count=1)
        self.assertFalse(AIUsageLog.objects.get().usage_is_estimated)

    def test_conflicting_or_missing_evidence_aborts_the_batch(self):
        self.recover()
        self.recover()
        row = AIUsageLog.objects.first()
        row.evidence = {'sourceId': 'wrong'}
        row.save(update_fields=['evidence'])
        with self.assertRaises(RecoveryEvidenceError):
            self.estimate(apply=True, expected_count=2)
        self.assertFalse(AIUsageLog.objects.filter(usage_is_estimated=True).exists())

    def test_write_failure_rolls_back_the_entire_batch(self):
        self.recover()
        self.recover()
        from django.db.models.query import QuerySet
        update = QuerySet.update
        calls = 0

        def fail_second(query, **values):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise DatabaseError('simulated failure')
            return update(query, **values)

        with patch.object(QuerySet, 'update', fail_second):
            with self.assertRaises(DatabaseError):
                self.estimate(apply=True, expected_count=2)
        self.assertFalse(AIUsageLog.objects.filter(usage_is_estimated=True).exists())

    def test_pricing_overrides_are_snapshotted_and_invalid_prices_abort(self):
        draft = self.recover()
        with override_settings(AI_USAGE_PRICING_USD_PER_MILLION={CONFIRMED_MODEL: {'input': '2', 'cached_input': '0.1', 'output': '3'}}):
            usage, cost, prices, _ = estimate_draft_tokens(draft)
            self.assertEqual(cost, (Decimal(usage['input_tokens']) * 2 + Decimal(usage['output_tokens']) * 3) / 1000000)
            self.assertEqual(prices['source'], 'operator_override')
        with override_settings(AI_USAGE_PRICING_USD_PER_MILLION={CONFIRMED_MODEL: {'input': 'invalid'}}):
            with self.assertRaises(RecoveryEvidenceError):
                self.estimate(apply=True, expected_count=1)
        self.assertFalse(AIUsageLog.objects.get().usage_is_estimated)

    def test_command_defaults_to_read_only_and_apply_requires_reviewed_count(self):
        self.recover()
        stream = io.StringIO()
        call_command('estimate_ai_usage_history', '--model=gpt-5.6-luna', stdout=stream)
        self.assertEqual(json.loads(stream.getvalue())['mode'], 'dry_run')
        self.assertFalse(AIUsageLog.objects.get().usage_is_estimated)
        with self.assertRaises(CommandError):
            call_command('estimate_ai_usage_history', '--model=gpt-5.6-luna', '--apply')
        call_command('estimate_ai_usage_history', '--model=gpt-5.6-luna', '--expected-count=1', '--apply', stdout=io.StringIO())
        self.assertTrue(AIUsageLog.objects.get().usage_is_estimated)


class AIHistoryEstimationApiTests(RecoveryFixture, APITestCase):
    def test_estimates_are_explicit_in_mixed_and_all_estimated_metrics_and_history(self):
        self.draft(CUTOFF - timedelta(days=1))
        admin = User.objects.create_superuser(username='estimate-admin', full_name='Estimate admin')
        with patch('apps.platform.services.ai_history_recovery.historical_cutoff', return_value=CUTOFF):
            recover_catalog_usage(apply=True, expected_count=1)
        with patch('apps.platform.services.ai_history_estimation.historical_cutoff', return_value=CUTOFF):
            estimate_recovered_catalog_usage(model=CONFIRMED_MODEL, apply=True, expected_count=1)
        recovered = AIUsageLog.objects.get()
        self.client.force_authenticate(admin)
        query = {'from': (CUTOFF - timedelta(days=2)).isoformat(), 'to': (CUTOFF + timedelta(days=2)).isoformat()}
        all_estimated = self.client.get('/api/v1/admin/ai-usage/summary/', query).data['totals']
        self.assertEqual((all_estimated['estimatedUsageCount'], all_estimated['missingUsageCount']), (1, 0))
        live = AIUsageLog.objects.create(feature='catalog_menu', model=CONFIRMED_MODEL, status='success',
            input_tokens=20, output_tokens=10, cached_input_tokens=0, total_tokens=30, estimated_cost_usd=Decimal('0.001'), duration_ms=123)
        AIUsageLog.objects.filter(pk=live.pk).update(created_at=CUTOFF + timedelta(seconds=1))
        totals = self.client.get('/api/v1/admin/ai-usage/summary/', query).data['totals']
        self.assertEqual((totals['requestCount'], totals['estimatedUsageCount']), (2, 1))
        self.assertEqual(totals['estimatedTokenCount'], recovered.total_tokens)
        self.assertEqual(totals['totalTokens'], recovered.total_tokens + 30)
        self.assertEqual(totals['averageDurationMs'], 123)
        results = self.client.get('/api/v1/admin/ai-usage/requests/', query).data['results']
        estimated_row = next(row for row in results if row['usageIsEstimated'])
        self.assertEqual(estimated_row['usageEstimation']['modelBasis'], 'operator_confirmed')
        self.assertEqual(estimated_row['usageEstimation']['basis'], 'saved_catalog_draft')
        self.assertIsNone(estimated_row['cachedInputTokens'])
        self.assertIsNone(next(row for row in results if not row['usageIsEstimated'])['usageEstimation'])


class HistoryEstimateVerifierTests(SimpleTestCase):
    def test_private_verification_allows_concurrent_live_writes_and_uses_matching_price_rounding(self):
        old = {'source': 'catalog_draft', 'usage_is_estimated': False, 'model': 'unknown',
               'input_tokens': None, 'cached_input_tokens': None, 'output_tokens': None,
               'total_tokens': None, 'estimated_cost_usd': None, 'duration_ms': None}
        estimated = {**old, 'model': CONFIRMED_MODEL, 'usage_is_estimated': True,
                     'input_tokens': 1, 'output_tokens': 0, 'total_tokens': 1,
                     'estimated_cost_usd': '0.000000000001',
                     'pricing': {'input': '0.0000005', 'output': '0'},
                     'evidence': {'usageEstimate': {'method': ESTIMATION_METHOD, 'modelBasis': 'operator_confirmed'}}}
        before = [{'pk': 'historical', 'fields': old}, {'pk': 'live', 'fields': {'source': 'live', 'usage_is_estimated': False}}]
        after = [{'pk': 'historical', 'fields': estimated}, before[1],
                 {'pk': 'new-live', 'fields': {'source': 'live', 'usage_is_estimated': False}}]
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'before.json', Path(directory) / 'after.json'
            first.write_text(json.dumps(before))
            second.write_text(json.dumps(after))
            output = io.StringIO()
            with patch.object(sys, 'argv', ['verify', str(first), str(second), '1']), patch('sys.stdout', output):
                runpy.run_path(str(settings.BASE_DIR / 'ops' / 'verify-ai-history-estimates.py'))
            result = json.loads(output.getvalue())
            self.assertEqual(result['concurrentLiveRows'], '1')
            self.assertEqual(result['liveRowsUnchanged'], '1')
            self.assertEqual(result['estimatedTotalCostUsd'], '1E-12')
