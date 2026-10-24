import json
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.platform.models import AIUsageLog
from apps.platform.services.ai_pricing import PRICING_SOURCE_URL, PRICING_VERIFIED_AT, estimated_cost
from apps.platform.services.ai_usage import audit_ai_usage


def counts(incoming=1000, cached=200, outgoing=100, **overrides):
    return {'input_tokens': incoming, 'cached_input_tokens': cached, 'output_tokens': outgoing,
            'total_tokens': incoming + outgoing, **overrides}


@override_settings(AI_USAGE_PRICING_USD_PER_MILLION={})
class StandardAIPricingTests(SimpleTestCase):
    def test_cached_input_is_a_subset_not_a_second_full_input_charge(self):
        cost, pricing = estimated_cost('gpt-5.6-luna', counts())
        self.assertEqual(cost, Decimal('0.000284'))
        self.assertEqual({key: pricing[key] for key in ('input', 'cached_input', 'output')},
                         {'input': '0.20', 'cached_input': '0.02', 'output': '1.20'})
        self.assertEqual(pricing['source'], 'openai_standard')
        self.assertEqual(pricing['source_url'], PRICING_SOURCE_URL)
        self.assertEqual(pricing['verified_at'], PRICING_VERIFIED_AT)
        self.assertEqual(pricing['context_tier'], 'short')
        self.assertEqual(pricing['unit'], 'usd_per_million_tokens')

    def test_all_verified_models_use_long_rates_only_above_exact_boundary(self):
        expected = {
            'gpt-5.6-luna': (('0.20', '0.02', '1.20'), ('0.40', '0.04', '1.80')),
            'gpt-5.6-terra': (('2', '0.20', '12'), ('4', '0.40', '18')),
            'gpt-5.6-sol': (('4', '0.40', '20'), ('8', '0.80', '30')),
        }
        for model, tiers in expected.items():
            for incoming, tier, rates in ((272000, 'short', tiers[0]), (272001, 'long', tiers[1])):
                with self.subTest(model=model, incoming=incoming):
                    # All input is cached: tier selection still uses total input,
                    # not only the uncached part or input + output.
                    cost, pricing = estimated_cost(model, counts(incoming=incoming, cached=incoming, outgoing=100))
                    self.assertEqual(tuple(pricing[key] for key in ('input', 'cached_input', 'output')), rates)
                    self.assertEqual(pricing['context_tier'], tier)
                    self.assertEqual(cost, (incoming * Decimal(rates[1]) + 100 * Decimal(rates[2])) / 1000000)
        _, short = estimated_cost('gpt-5.6-luna', counts(incoming=272000, outgoing=100000))
        self.assertEqual(short['context_tier'], 'short')

    def test_model_names_are_exact_and_missing_or_malformed_usage_is_not_zero(self):
        for model in ('gpt-5.6-luna-latest', 'gpt-5.6-luna-2026-10-24', 'GPT-5.6-luna', 'gpt-unknown', ''):
            with self.subTest(model=model):
                self.assertEqual(estimated_cost(model, counts()), (None, {}))
        for invalid in ({}, None, counts(cached_input_tokens=None), counts(total_tokens=None),
                        counts(total_tokens=999), counts(cached_input_tokens=1001),
                        counts(input_tokens=True), counts(output_tokens=-1), counts(input_tokens='1000')):
            with self.subTest(usage=invalid):
                self.assertEqual(estimated_cost('gpt-5.6-luna', invalid), (None, {}))
        self.assertEqual(estimated_cost('gpt-5.6-luna', counts(0, 0, 0))[0], Decimal('0'))

    @override_settings(AI_USAGE_PRICING_USD_PER_MILLION=None)
    def test_environment_overrides_known_model_and_absent_override_uses_default(self):
        rates = {'gpt-5.6-luna': {'input': '2', 'cached_input': '0.5', 'output': '4'}}
        with patch.dict('os.environ', {'AI_USAGE_PRICING_USD_PER_MILLION': json.dumps(rates)}):
            cost, pricing = estimated_cost('gpt-5.6-luna', counts())
            self.assertEqual(cost, Decimal('0.0021'))
            self.assertEqual(pricing['source'], 'operator_override')
            self.assertEqual(pricing['context_tier'], 'custom')
            # Legacy flat overrides apply to all request sizes as configured.
            self.assertEqual(estimated_cost('gpt-5.6-luna', counts(incoming=300000))[1]['input'], '2')
            self.assertEqual(estimated_cost('gpt-5.6-sol', counts())[1]['source'], 'openai_standard')
        with patch.dict('os.environ', {'AI_USAGE_PRICING_USD_PER_MILLION': ''}):
            self.assertEqual(estimated_cost('gpt-5.6-luna', counts())[0], Decimal('0.000284'))

    def test_django_setting_has_precedence_over_environment(self):
        env = {'gpt-5.6-luna': {'input': '100', 'cached_input': '100', 'output': '100'}}
        with patch.dict('os.environ', {'AI_USAGE_PRICING_USD_PER_MILLION': json.dumps(env)}):
            self.assertEqual(estimated_cost('gpt-5.6-luna', counts())[0], Decimal('0.000284'))
        with self.settings(AI_USAGE_PRICING_USD_PER_MILLION={'custom-model': {'input': '0', 'cached_input': '0', 'output': '0'}}):
            self.assertEqual(estimated_cost('custom-model', counts())[0], Decimal('0'))

    def test_invalid_explicit_override_does_not_silently_fall_back(self):
        for configured in ('{bad json', '[]', 'x' * 65537, [],
                           {'gpt-5.6-luna': None}, {'gpt-5.6-luna': {}},
                           {'gpt-5.6-luna': {'input': '-1', 'cached_input': '0', 'output': '1'}},
                           {'gpt-5.6-luna': {'input': 'NaN', 'cached_input': '0', 'output': '1'}}):
            with self.subTest(configured=str(configured)[:80]), self.settings(AI_USAGE_PRICING_USD_PER_MILLION=configured):
                self.assertEqual(estimated_cost('gpt-5.6-luna', counts()), (None, {}))


@override_settings(AI_USAGE_PRICING_USD_PER_MILLION={})
class AIUsageCostBackfillTests(TestCase):
    def event(self, **overrides):
        return AIUsageLog.objects.create(**{
            'feature': 'catalog_menu', 'model': 'gpt-5.6-luna', 'status': 'success', **counts(), **overrides,
        })

    def run_command(self, *args):
        output = StringIO()
        call_command('backfill_ai_usage_costs', *args, stdout=output)
        return output.getvalue()

    def test_default_and_explicit_dry_run_make_no_changes(self):
        row = self.event()
        before = AIUsageLog.objects.values().get(pk=row.pk)
        for args in ((), ('--dry-run',)):
            output = self.run_command(*args)
            self.assertIn('DRY RUN: eligible=1, skipped=0, applied=0', output)
            self.assertIn('estimated_usd=0.000284000000', output)
            self.assertEqual(AIUsageLog.objects.values().get(pk=row.pk), before)

    def test_apply_prices_only_null_cost_complete_openai_records_and_is_idempotent(self):
        first = self.event()
        # Failed responses can still contain actual chargeable usage.
        failure = self.event(status='error', error_code='provider_incomplete')
        zero = self.event(**counts(0, 0, 0))
        priced = self.event(estimated_cost_usd=Decimal('0.123'), pricing={'source': 'historic'})
        unknown = self.event(model='unknown-model')
        missing = self.event(cached_input_tokens=None)
        invalid = self.event(total_tokens=999)
        other_provider = self.event(provider='another-provider')
        untouched = {row.pk: AIUsageLog.objects.values().get(pk=row.pk)
                     for row in (priced, unknown, missing, invalid, other_provider)}
        original = AIUsageLog.objects.values().get(pk=first.pk)
        self.assertIn('APPLIED: eligible=3, skipped=3, applied=3', self.run_command('--apply'))
        first.refresh_from_db()
        failure.refresh_from_db()
        zero.refresh_from_db()
        self.assertEqual(first.estimated_cost_usd, Decimal('0.000284'))
        self.assertEqual(failure.estimated_cost_usd, first.estimated_cost_usd)
        self.assertEqual(zero.estimated_cost_usd, Decimal('0'))
        self.assertEqual(first.pricing['verified_at'], PRICING_VERIFIED_AT)
        after = AIUsageLog.objects.values().get(pk=first.pk)
        for field in original.keys() - {'estimated_cost_usd', 'pricing', 'updated_at'}:
            self.assertEqual(after[field], original[field])
        for pk, before in untouched.items():
            self.assertEqual(AIUsageLog.objects.values().get(pk=pk), before)
        snapshot = list(AIUsageLog.objects.order_by('id').values())
        with self.settings(AI_USAGE_PRICING_USD_PER_MILLION={'gpt-5.6-luna': {'input': '9', 'cached_input': '9', 'output': '9'}}):
            self.assertIn('eligible=0, skipped=3, applied=0', self.run_command('--apply'))
        self.assertEqual(list(AIUsageLog.objects.order_by('id').values()), snapshot)
        self.assertEqual(AIUsageLog.objects.count(), 8)

    def test_backfill_uses_same_long_context_and_override_snapshot_as_live_audit(self):
        row = self.event(**counts(272001, 1000, 100))
        expected, snapshot = estimated_cost(row.model, counts(272001, 1000, 100))
        self.run_command('--apply')
        row.refresh_from_db()
        self.assertEqual((row.estimated_cost_usd, row.pricing), (expected, snapshot))
        with self.settings(AI_USAGE_PRICING_USD_PER_MILLION={'custom-model': {'input': '2', 'cached_input': '.5', 'output': '4'}}):
            custom = self.event(model='custom-model')
            self.run_command('--apply')
            custom.refresh_from_db()
            self.assertEqual(custom.estimated_cost_usd, Decimal('.0021'))
            self.assertEqual(custom.pricing['source'], 'operator_override')

    def test_live_audit_uses_verified_default_snapshot_without_provider_call(self):
        with audit_ai_usage('catalog_menu', 'gpt-5.6-luna') as audit:
            audit.observe_result({'model': 'gpt-5.6-luna', 'usage': {
                'input_tokens': 465, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 62, 'total_tokens': 527,
            }})
        row = AIUsageLog.objects.get()
        self.assertEqual(row.estimated_cost_usd, Decimal('0.0001674'))
        self.assertEqual(row.pricing['source'], 'openai_standard')
