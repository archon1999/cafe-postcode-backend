import io
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.catalog.models import CatalogItem
from apps.catalog_assistant.models import CatalogDraft
from apps.platform.models import AIUsageLog, BusinessPartner
from apps.platform.services.ai_history_recovery import RecoveryEvidenceError, historical_cutoff, recover_catalog_usage
from apps.restaurants.models import Restaurant
from apps.users.models import User

CUTOFF = datetime(2026, 10, 24, 19, 42, tzinfo=dt_timezone.utc)


class RecoveryFixture:
    @classmethod
    def setUpTestData(cls):
        cls.partner = BusinessPartner.objects.create(inn='ai-recovery-fixture', company_name='Recovery partner')
        cls.branch = Restaurant.objects.create(name='Historical branch', business_partner=cls.partner)
        cls.owner = User.objects.create_user(username='historical-owner', full_name='Historical operator')

    def draft(self, at, rows=None):
        row = CatalogDraft.objects.create(owner=self.owner, restaurant=self.branch,
            rows=[{'name': 'PRIVATE_SOURCE sk-private', 'evidence': 'PRIVATE_UPLOAD'}] if rows is None else rows,
            expires_at=at + timedelta(days=1))
        CatalogDraft.objects.filter(pk=row.pk).update(created_at=at)
        row.refresh_from_db()
        return row


class AIHistoryRecoveryTests(RecoveryFixture, TestCase):
    def setUp(self):
        self.cutoff = patch('apps.platform.services.ai_history_recovery.historical_cutoff', return_value=CUTOFF)
        self.cutoff.start()
        self.addCleanup(self.cutoff.stop)

    def test_dry_run_is_read_only_and_omits_post_tracking_or_unproven_drafts(self):
        old = self.draft(CUTOFF - timedelta(days=30))
        self.draft(CUTOFF)
        self.draft(CUTOFF + timedelta(seconds=1))
        self.draft(CUTOFF - timedelta(days=1), rows=[])
        before = list(CatalogDraft.objects.order_by('id').values())
        report = recover_catalog_usage()
        self.assertEqual((report['eligible'], report['willCreate'], report['created']), (1, 1, 0))
        self.assertEqual(report['skippedUnprovenDrafts'], 1)
        self.assertEqual(report['firstEvidenceAt'], old.created_at.isoformat())
        self.assertFalse(AIUsageLog.objects.exists())
        self.assertEqual(list(CatalogDraft.objects.order_by('id').values()), before)

    def test_apply_preserves_provenance_original_time_and_unknown_usage_without_copying_content(self):
        old = self.draft(CUTOFF - timedelta(days=30))
        before_items = CatalogItem.objects.count()
        result = recover_catalog_usage(apply=True, expected_count=1)
        self.assertEqual(result['created'], 1)
        row = AIUsageLog.objects.get()
        self.assertEqual(row.created_at, old.created_at)
        self.assertGreater(row.recovered_at, row.created_at)
        self.assertEqual((row.source, row.feature, row.status), ('catalog_draft', 'catalog_menu', 'success'))
        self.assertEqual((row.restaurant_id, row.business_partner_id, row.user_id),
                         (old.restaurant_id, self.partner.pk, old.owner_id))
        self.assertEqual((row.restaurant_name, row.business_partner_name, row.user_name),
                         ('Historical branch', 'Recovery partner', 'Historical operator'))
        self.assertEqual(row.evidence, {'kind': 'catalog_draft', 'sourceId': str(old.pk), 'occurredAtBasis': 'draft_created_at'})
        self.assertEqual(row.model, 'unknown')
        for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens', 'estimated_cost_usd', 'duration_ms'):
            self.assertIsNone(getattr(row, field))
        self.assertEqual((row.request_id, row.provider_status, row.pricing), ('', '', {}))
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(row.__dict__, default=str))
        self.assertNotIn('PRIVATE_UPLOAD', json.dumps(row.__dict__, default=str))
        self.assertNotIn('sk-private', json.dumps(row.__dict__, default=str))
        self.assertEqual(CatalogItem.objects.count(), before_items)
        old.refresh_from_db()
        self.assertIsNone(old.committed_at)

    def test_repeat_is_idempotent_and_live_rows_remain_byte_for_byte_unchanged(self):
        self.draft(CUTOFF - timedelta(days=1))
        live = AIUsageLog.objects.create(feature='catalog_menu', model='priced', status='success',
            input_tokens=10, cached_input_tokens=0, output_tokens=5, total_tokens=15,
            estimated_cost_usd=Decimal('0.005'), request_id='req_original')
        before = AIUsageLog.objects.values().get(pk=live.pk)
        recover_catalog_usage(apply=True, expected_count=1)
        imported = AIUsageLog.objects.values().get(source='catalog_draft')
        result = recover_catalog_usage(apply=True, expected_count=1)
        self.assertEqual((result['created'], result['alreadyRecovered']), (0, 1))
        self.assertEqual(AIUsageLog.objects.count(), 2)
        self.assertEqual(AIUsageLog.objects.values().get(pk=live.pk), before)
        self.assertEqual(AIUsageLog.objects.values().get(source='catalog_draft'), imported)

    def test_expected_count_and_conflicting_evidence_fail_before_any_writes(self):
        draft = self.draft(CUTOFF - timedelta(days=1))
        with self.assertRaises(RecoveryEvidenceError):
            recover_catalog_usage(apply=True, expected_count=2)
        self.assertFalse(AIUsageLog.objects.exists())
        AIUsageLog.objects.create(feature='inventory_analysis', model='known', status='success',
            recovery_key=f'catalog_draft:{draft.pk}')
        with self.assertRaises(RecoveryEvidenceError):
            recover_catalog_usage(apply=True, expected_count=1)
        self.assertEqual(AIUsageLog.objects.count(), 1)

    def test_failed_insert_rolls_back_the_entire_batch(self):
        self.draft(CUTOFF - timedelta(days=2))
        self.draft(CUTOFF - timedelta(days=1))
        create = AIUsageLog.objects.create
        calls = 0

        def fail_second(**values):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError('simulated write failure')
            return create(**values)

        with patch.object(AIUsageLog.objects, 'create', side_effect=fail_second):
            with self.assertRaises(IntegrityError):
                recover_catalog_usage(apply=True, expected_count=2)
        self.assertFalse(AIUsageLog.objects.exists())

    def test_command_requires_reviewed_count_to_apply_and_defaults_to_dry_run(self):
        self.draft(CUTOFF - timedelta(days=1))
        output = io.StringIO()
        call_command('recover_ai_usage_history', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['mode'], 'dry_run')
        self.assertFalse(AIUsageLog.objects.exists())
        with self.assertRaises(CommandError):
            call_command('recover_ai_usage_history', '--apply')
        with self.assertRaises(CommandError):
            call_command('recover_ai_usage_history', '--expected-count=-1')
        call_command('recover_ai_usage_history', '--apply', '--expected-count=1', stdout=io.StringIO())
        self.assertEqual(AIUsageLog.objects.count(), 1)


class AIHistoryRecoveryApiTests(RecoveryFixture, APITestCase):
    def test_recovered_history_is_visible_without_changing_tracking_start_or_subtotal(self):
        draft = self.draft(CUTOFF - timedelta(days=10))
        admin = User.objects.create_superuser(username='recovery-superadmin', full_name='Recovery admin')
        live = AIUsageLog.objects.create(feature='catalog_menu', model='known', status='success',
            input_tokens=10, cached_input_tokens=0, output_tokens=5, total_tokens=15,
            estimated_cost_usd=Decimal('0.005'), duration_ms=150)
        AIUsageLog.objects.filter(pk=live.pk).update(created_at=CUTOFF + timedelta(minutes=1))
        with patch('apps.platform.services.ai_history_recovery.historical_cutoff', return_value=CUTOFF):
            recover_catalog_usage(apply=True, expected_count=1)
        self.client.force_authenticate(admin)
        query = {'from': (CUTOFF - timedelta(days=30)).isoformat(), 'to': (CUTOFF + timedelta(days=1)).isoformat()}
        response = self.client.get('/api/v1/admin/ai-usage/summary/', query)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['trackingStartedAt'], (CUTOFF + timedelta(minutes=1)).isoformat())
        totals = response.data['totals']
        self.assertEqual((totals['requestCount'], totals['recoveredRequestCount']), (2, 1))
        self.assertEqual((totals['totalTokens'], totals['missingUsageCount'], totals['unpricedRequestCount']), (15, 1, 1))
        self.assertEqual(Decimal(totals['estimatedCostUsd']), Decimal('0.005'))
        self.assertEqual(totals['averageDurationMs'], 150)
        history = self.client.get('/api/v1/admin/ai-usage/requests/', query)
        self.assertEqual(history.status_code, 200)
        recovered = next(row for row in history.data['results'] if row['source'] == 'catalog_draft')
        self.assertEqual(recovered['evidence']['sourceId'], str(draft.pk))
        self.assertIsNone(recovered['totalTokens'])
        self.assertIsNone(recovered['durationMs'])
        self.assertIsNone(recovered['estimatedCostUsd'])


class HistoricalCutoffTests(TestCase):
    @patch('apps.platform.services.ai_history_recovery.MigrationRecorder.Migration.objects.filter')
    def test_missing_original_tracking_boundary_is_not_guessed(self, migrations):
        migrations.return_value.first.return_value = None
        with self.assertRaises(RecoveryEvidenceError):
            historical_cutoff()

    @patch('apps.platform.services.ai_history_recovery.MigrationRecorder.Migration.objects.filter')
    def test_original_migration_and_live_boundary_exclude_recovered_dates(self, migrations):
        migrations.return_value.first.return_value = SimpleNamespace(applied=CUTOFF)
        self.assertEqual(historical_cutoff(), CUTOFF)
        recovered = AIUsageLog.objects.create(source='catalog_draft', feature='catalog_menu', model='unknown', status='success')
        AIUsageLog.objects.filter(pk=recovered.pk).update(created_at=CUTOFF - timedelta(days=30))
        self.assertEqual(historical_cutoff(), CUTOFF)
        live = AIUsageLog.objects.create(feature='catalog_menu', model='known', status='success')
        AIUsageLog.objects.filter(pk=live.pk).update(created_at=CUTOFF - timedelta(minutes=1))
        self.assertEqual(historical_cutoff(), CUTOFF - timedelta(minutes=1))
