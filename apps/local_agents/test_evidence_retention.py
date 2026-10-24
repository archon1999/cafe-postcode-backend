import copy
import io
import json
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.local_agents.evidence_archive import FileArchiveStore, archive_store
from apps.local_agents.evidence_retention import (
    archive_payloads, compact_operation, rehydrate_operation, run_retention,
)
from apps.local_agents.evidence_store import (
    EvidenceUnavailable, body_reference, resolve_body, store_body,
)
from apps.local_agents.models import (
    AgentEvidenceArchive, AgentEvidencePayload, AgentEvidencePolicy,
    LocalAgent, LocalAgentMutationAttempt, LocalAgentMutationInbox, LocalAgentMutationReceipt,
)
from apps.local_agents.mutation_inbox import _hash, receive_and_apply
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.local_agents.mutation_reconciliation import request_hash
from apps.restaurants.models import Restaurant
from apps.sales.models import Order


class AgentEvidenceRetentionTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(
            AGENT_EVIDENCE_ARCHIVE_BACKEND='file', AGENT_EVIDENCE_ARCHIVE_ROOT=self.temp.name,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.now = timezone.now()
        self.old = self.now - timedelta(days=180)
        self.restaurant = Restaurant.objects.create(name='Evidence pilot')
        self.agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.policy = AgentEvidencePolicy.objects.create(
            restaurant=self.restaurant, writes_enabled=True, compaction_enabled=True, archive_enabled=True,
        )
        self.order = Order.objects.create(restaurant=self.restaurant, channel='takeaway', status='closed',
                                          closed_at=self.old, total=96000)
        Order.objects.filter(pk=self.order.pk).update(created_at=self.old, updated_at=self.old)
        self.operation = {
            'operationId': 'evidence:' + str(uuid.uuid4()), 'userId': str(uuid.uuid4()),
            'method': 'POST', 'path': f'/api/v1/pos/billing/orders/{self.order.pk}/pay/',
            'body': {'method': 'cash', 'amount': 96000}, 'occurredAt': self.old.isoformat(),
        }
        self.response = {'orderId': str(self.order.pk), 'amount': 96000, 'snapshot': 'original ' * 250}

    def apply_payment(self, operation):
        payment = Payment.objects.create(order=self.order, amount=96000, method='cash', status='succeeded',
                                         paid_at=self.old, edge_operation_id=operation['operationId'])
        response = {**self.response, 'paymentId': str(payment.pk)}
        LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant, operation_id=operation['operationId'], user_id=operation['userId'],
            method=operation['method'], path=operation['path'],
            request_hash=request_hash(user_id=operation['userId'], method=operation['method'], path=operation['path'], body=operation['body']),
            response_status=201,
            response_body=store_body(restaurant_id=self.restaurant.pk, operation_id=operation['operationId'], body=response),
        )
        return {'operationId': operation['operationId'], 'ok': True, 'status': 201, 'body': response}

    def seed(self, *, inline=False, operation=None):
        operation = operation or self.operation
        if inline:
            AgentEvidencePolicy.objects.filter(pk=self.policy.pk).update(writes_enabled=False)
        first = receive_and_apply(agent=self.agent, operation=operation, apply=self.apply_payment)
        self.assertTrue(first['ok'], first)
        inbox = LocalAgentMutationInbox.objects.get(operation_id=operation['operationId'])
        LocalAgentMutationInbox.objects.filter(pk=inbox.pk).update(created_at=self.old, updated_at=self.old, applied_at=self.old)
        LocalAgentMutationReceipt.objects.filter(operation_id=operation['operationId']).update(created_at=self.old, updated_at=self.old)
        inbox.attempts.update(created_at=self.old, updated_at=self.old)
        AgentEvidencePolicy.objects.filter(pk=self.policy.pk).update(writes_enabled=True)
        return first

    def archive(self):
        report = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertGreater(report.get('archived', 0), 0, report)
        return report

    def counts(self):
        return (Payment.objects.count(), PaymentRefund.objects.count(), Receipt.objects.count(), Order.objects.count())

    def test_new_responses_shared_once_and_wire_body_unchanged(self):
        first = self.seed()
        inbox = LocalAgentMutationInbox.objects.get()
        receipt = LocalAgentMutationReceipt.objects.get()
        self.assertEqual(inbox.last_result['body'], receipt.response_body)
        self.assertEqual(inbox.attempts.get().result['body'], receipt.response_body)
        self.assertEqual(AgentEvidencePayload.objects.count(), 1)
        self.assertEqual(resolve_body(restaurant_id=self.restaurant.pk, operation_id=inbox.operation_id, body=receipt.response_body), first['body'])
        self.assertNotIn('__agent_evidence_body__', json.dumps(first))

    def test_archive_old_payment_replay_returns_exact_snapshot_without_execution(self):
        first = self.seed()
        before = self.counts()
        self.archive()
        Order.objects.filter(pk=self.order.pk).update(total=123)
        apply = Mock(side_effect=AssertionError('Old payment must never execute again'))
        replay = receive_and_apply(agent=self.agent, operation=self.operation, apply=apply)
        self.assertEqual(replay['body'], first['body'])
        self.assertTrue(replay['replayed'])
        self.assertTrue(replay['applied'])
        self.assertEqual(self.counts(), before)
        apply.assert_not_called()

    def test_changed_hash_and_other_restaurant_conflict_even_if_archive_is_down(self):
        self.seed()
        self.archive()
        changed = copy.deepcopy(self.operation)
        changed['occurredAt'] = (self.old + timedelta(seconds=1)).isoformat()
        other = Restaurant.objects.create(name='Other branch')
        other_agent, _ = LocalAgent.issue_for_restaurant(restaurant=other)
        with patch('apps.local_agents.evidence_archive.FileArchiveStore.get', side_effect=OSError('down')):
            result = receive_and_apply(agent=self.agent, operation=changed, apply=Mock())
            cross_tenant = receive_and_apply(agent=other_agent, operation=self.operation, apply=Mock())
        self.assertEqual(result['status'], 409)
        self.assertEqual(result['code'], 'OPERATION_ID_CONFLICT')
        self.assertEqual(cross_tenant['status'], 409)

    def test_legacy_receipt_only_replays_cold_body_before_any_actor_dispatch(self):
        first = self.seed()
        self.archive()
        LocalAgentMutationAttempt.objects.all().delete()
        LocalAgentMutationInbox.objects.all().delete()
        before = self.counts()
        processor = LocalAgentMutationProcessor()
        with patch.object(processor, '_dispatch', side_effect=AssertionError('must not dispatch')):
            result = processor.process(agent=self.agent, operation=self.operation)
        self.assertTrue(result['replayed'], result)
        self.assertEqual(result['body'], first['body'])
        self.assertEqual(self.counts(), before)

    def test_legacy_changed_request_hash_is_conflict(self):
        self.seed()
        self.archive()
        LocalAgentMutationAttempt.objects.all().delete()
        LocalAgentMutationInbox.objects.all().delete()
        changed = copy.deepcopy(self.operation)
        changed['body']['amount'] = 1
        with patch('apps.local_agents.evidence_archive.FileArchiveStore.get', side_effect=OSError('down')):
            result = LocalAgentMutationProcessor().process(agent=self.agent, operation=changed)
        self.assertEqual(result['code'], 'OPERATION_ID_CONFLICT')
        self.assertEqual(result['status'], 409)
        self.assertFalse(LocalAgentMutationInbox.objects.exists(), 'A changed legacy envelope must not reserve the operation ID')

    def test_signed_bulk_http_replay_contains_exact_body_and_never_a_storage_reference(self):
        from apps.local_agents.tests_support import bind_agent_client
        first = self.seed()
        self.archive()
        client = APIClient()
        bind_agent_client(client, self.agent, self.token)
        before = self.counts()
        with patch.object(LocalAgentMutationProcessor, '_dispatch', side_effect=AssertionError('must not dispatch')):
            response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [self.operation]},
                                   format='json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(response.status_code, 200)
        result = response.json()['results'][0]
        self.assertEqual(result['body'], first['body'])
        self.assertTrue(result['replayed'])
        self.assertNotIn('__agent_evidence_body__', response.content.decode())
        self.assertEqual(self.counts(), before)

    def test_bulk_replay_reads_shared_bundle_once_per_request(self):
        from apps.local_agents.tests_support import bind_agent_client
        first = self.seed()
        extra = {**self.operation, 'operationId': 'second-old-payment'}
        second = self.seed(operation=extra)
        self.archive()
        client = APIClient()
        bind_agent_client(client, self.agent, self.token)
        original_get = FileArchiveStore.get
        with patch.object(FileArchiveStore, 'get', autospec=True,
                          side_effect=lambda store, key: original_get(store, key)) as get:
            response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [self.operation, extra]},
                                   format='json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['body'] for row in response.json()['results']], [first['body'], second['body']])
        self.assertEqual(get.call_count, 1)

    def test_missing_or_corrupt_archive_fails_closed_and_independent_order_continues(self):
        self.seed()
        self.archive()
        before = self.counts()
        for data in (OSError('unavailable'), b'corrupted bundle'):
            with self.subTest(data=type(data).__name__):
                options = {'side_effect': data} if isinstance(data, Exception) else {'return_value': data}
                with patch('apps.local_agents.evidence_archive.FileArchiveStore.get', **options):
                    apply = Mock(side_effect=AssertionError('must never reapply'))
                    result = receive_and_apply(agent=self.agent, operation=self.operation, apply=apply)
                self.assertFalse(result['ok'])
                self.assertTrue(result['retryable'])
                self.assertEqual(result['code'], 'EVIDENCE_TEMPORARILY_UNAVAILABLE')
                apply.assert_not_called()
        self.assertEqual(self.counts(), before)
        fresh = {**self.operation, 'operationId': 'new-independent'}
        result = receive_and_apply(agent=self.agent, operation=fresh, apply=lambda _: {'ok': True, 'status': 200, 'body': {'id': 'new'}})
        self.assertTrue(result['ok'])
        self.assertEqual(LocalAgentMutationInbox.objects.get(operation_id=self.operation['operationId']).state, 'applied')

    def test_compaction_preserves_original_operation_hashes_times_and_dependency_certificate(self):
        first = self.seed(inline=True)
        inbox = LocalAgentMutationInbox.objects.get()
        metadata = {'dependencyPolicy': 'order_isolation_v1', 'deferredOrderDependencies': ['blocked-predecessor']}
        LocalAgentMutationInbox.objects.filter(pk=inbox.pk).update(last_result={**inbox.last_result, **metadata})
        receipt = LocalAgentMutationReceipt.objects.get()
        original = (inbox.operation, inbox.payload_hash, receipt.request_hash, inbox.created_at, inbox.updated_at, inbox.applied_at)
        failed = LocalAgentMutationAttempt.objects.create(inbox=inbox, payload_hash=inbox.payload_hash,
                                                         result={'ok': False, 'status': 400, 'body': {'originalError': 'x' * 2000}})
        before_failure = failed.result
        report = run_retention(restaurant_id=self.restaurant.pk, apply=True)
        self.assertEqual(report['rows'], 3, report)
        inbox.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual((inbox.operation, inbox.payload_hash, receipt.request_hash, inbox.created_at, inbox.updated_at, inbox.applied_at), original)
        self.assertEqual(inbox.last_result['deferredOrderDependencies'], ['blocked-predecessor'])
        failed.refresh_from_db()
        self.assertEqual(failed.result, before_failure)
        self.assertEqual(resolve_body(restaurant_id=self.restaurant.pk, operation_id=inbox.operation_id, body=inbox.last_result['body']), first['body'])

    def test_dry_run_writes_nothing_and_is_default_for_command(self):
        self.seed(inline=True)
        original = LocalAgentMutationInbox.objects.get().last_result
        out = io.StringIO()
        call_command('agent_evidence_retention', restaurant=str(self.restaurant.pk), stdout=out)
        self.assertTrue(json.loads(out.getvalue())['dry_run'])
        self.assertEqual(AgentEvidencePayload.objects.count(), 0)
        self.assertEqual(LocalAgentMutationInbox.objects.get().last_result, original)
        self.policy.refresh_from_db()
        self.assertIsNone(self.policy.last_run_at)

    def test_maintenance_is_allowlisted_and_restart_is_idempotent(self):
        self.seed(inline=True)
        other = Restaurant.objects.create(name='Not allowlisted')
        with self.assertRaises(ValueError):
            run_retention(restaurant_id=other.pk, apply=True)
        first = run_retention(restaurant_id=self.restaurant.pk, apply=True, archive=True)
        second = run_retention(restaurant_id=self.restaurant.pk, apply=True, archive=True)
        self.assertEqual(first['rows'], 3)
        self.assertEqual(second['rows'], 0)
        self.assertEqual(second['archive']['archived'], 0)
        self.assertEqual(AgentEvidencePayload.objects.count(), 1)

    def test_failed_readback_leaves_hot_body_and_pauses_scheduler(self):
        self.seed()
        AgentEvidencePolicy.objects.filter(pk=self.policy.pk).update(schedule_enabled=True)
        with patch('apps.local_agents.evidence_archive.FileArchiveStore.get', return_value=b'bad readback'):
            with self.assertRaises(EvidenceUnavailable):
                run_retention(restaurant_id=self.restaurant.pk, apply=True, archive=True)
        self.assertIsNotNone(AgentEvidencePayload.objects.get().content)
        self.assertFalse(AgentEvidenceArchive.objects.exists())
        self.policy.refresh_from_db()
        self.assertFalse(self.policy.schedule_enabled)
        self.assertIsNone(self.policy.lease_token)
        replay = receive_and_apply(agent=self.agent, operation=self.operation, apply=Mock())
        self.assertTrue(replay['ok'])

    def test_crash_after_upload_before_finalize_keeps_hot_body_and_resumes(self):
        self.seed()
        with patch.object(AgentEvidenceArchive, 'save', side_effect=RuntimeError('crash after readback')):
            with self.assertRaises(RuntimeError):
                self.archive()
        self.assertIsNotNone(AgentEvidencePayload.objects.get().content)
        self.assertEqual(len(list(Path(self.temp.name).rglob('*.gz'))), 1)
        self.archive()
        self.assertEqual(AgentEvidenceArchive.objects.count(), 1)

    def test_unresolved_ancestor_protects_all_cold_payloads_in_branch(self):
        self.seed()
        operation = {**self.operation, 'operationId': 'pending-ancestor'}
        LocalAgentMutationInbox.objects.create(restaurant=self.restaurant, operation_id='pending-ancestor',
                                               payload_hash=_hash(operation), operation=operation, state='needs_review')
        report = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(report['blocked'], 'unresolved_inbox')
        self.assertIsNotNone(AgentEvidencePayload.objects.get().content)

    def test_open_order_protected_and_financial_thirty_day_floor(self):
        self.seed()
        inbox = LocalAgentMutationInbox.objects.get()
        recent = self.now - timedelta(days=20)
        LocalAgentMutationInbox.objects.filter(pk=inbox.pk).update(created_at=recent, updated_at=recent, applied_at=recent)
        report = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(report['skips'].get('not_old_and_settled'), 1)
        LocalAgentMutationInbox.objects.filter(pk=inbox.pk).update(created_at=self.old, updated_at=self.old, applied_at=self.old)
        Order.objects.filter(pk=self.order.pk).update(status='open')
        report = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(report['skips'].get('order_not_closed'), 1)

    def test_merge_into_open_session_and_recent_refund_stay_hot(self):
        from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
        self.seed()
        zone = ZoneOrCabin.objects.create(restaurant=self.restaurant, name='Zone')
        hall = Hall.objects.create(zone_or_cabin=zone, name='Hall')
        table = DiningTable.objects.create(hall=hall, name='Table')
        target = TableSession.objects.create(restaurant=self.restaurant, hall=hall, table=table)
        source = TableSession.objects.create(restaurant=self.restaurant, hall=hall, table=table,
                                            status='merged', closed_at=self.old, merged_into=target)
        TableSession.objects.filter(pk=source.pk).update(updated_at=self.old)
        Order.objects.filter(pk=self.order.pk).update(table_session=source)
        first = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(first['skips']['session_not_closed'], 1)
        Order.objects.filter(pk=self.order.pk).update(table_session=None)
        PaymentRefund.objects.create(payment=Payment.objects.get(), amount=1000)
        second = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(second['skips']['refund_not_settled_and_old'], 1)

    def test_reference_scope_hash_and_hot_corruption_are_fail_closed(self):
        self.seed()
        payload = AgentEvidencePayload.objects.get()
        reference = body_reference(payload)
        for restaurant_id, operation_id, body in (
            (uuid.uuid4(), payload.operation_id, reference),
            (self.restaurant.pk, 'other-operation', reference),
            (self.restaurant.pk, payload.operation_id, {'__agent_evidence_body__': {'v': 99}}),
        ):
            with self.assertRaises(EvidenceUnavailable):
                resolve_body(restaurant_id=restaurant_id, operation_id=operation_id, body=body)
        AgentEvidencePayload.objects.filter(pk=payload.pk).update(content={'body': {'corrupted': True}})
        with self.assertRaises(EvidenceUnavailable):
            resolve_body(restaurant_id=self.restaurant.pk, operation_id=payload.operation_id, body=reference)

    def test_archive_io_outside_transactions_and_prefetched_legacy_replay(self):
        first = self.seed()
        self.archive()
        LocalAgentMutationAttempt.objects.all().delete()
        LocalAgentMutationInbox.objects.all().delete()
        original = FileArchiveStore.get
        observations = []

        def checked_get(store, key):
            observations.append(connection.in_atomic_block)
            self.assertFalse(connection.in_atomic_block)
            return original(store, key)

        with patch.object(FileArchiveStore, 'get', checked_get):
            result = LocalAgentMutationProcessor().process(agent=self.agent, operation=self.operation)
        self.assertTrue(observations)
        self.assertEqual(result['body'], first['body'])
        with transaction.atomic(), self.assertRaises(EvidenceUnavailable):
            FileArchiveStore().get(AgentEvidenceArchive.objects.get().object_key)

    def test_pause_and_rehydrate_all_journals_before_old_code_rollback(self):
        first = self.seed()
        self.archive()
        with self.assertRaises(CommandError):
            call_command('agent_evidence_retention', restaurant=str(self.restaurant.pk), apply=True, rehydrate=True, stdout=io.StringIO())
        call_command('agent_evidence_retention', restaurant=str(self.restaurant.pk), apply=True, configure='pause', stdout=io.StringIO())
        self.assertEqual(rehydrate_operation(self.restaurant.pk, self.operation['operationId']), 3)
        self.assertEqual(LocalAgentMutationReceipt.objects.get().response_body, first['body'])
        self.assertEqual(LocalAgentMutationInbox.objects.get().last_result['body'], first['body'])
        self.assertEqual(LocalAgentMutationAttempt.objects.get().result['body'], first['body'])

    def test_public_media_path_and_overwrite_are_rejected(self):
        with override_settings(AGENT_EVIDENCE_ARCHIVE_ROOT=str(Path(self.temp.name) / 'media'), MEDIA_ROOT=str(Path(self.temp.name) / 'media')):
            with self.assertRaises(EvidenceUnavailable):
                archive_store().put('v1/test/item.jsonl.gz', b'private')
        store = FileArchiveStore()
        with self.assertRaises(EvidenceUnavailable):
            store.put('v1/../../media/item.jsonl.gz', b'private')
        store.put('v1/test/item.jsonl.gz', b'original')
        with self.assertRaises(FileExistsError):
            store.put('v1/test/item.jsonl.gz', b'replaced')
        self.assertEqual(store.get('v1/test/item.jsonl.gz'), b'original')

    def test_s3_requires_separate_bucket_and_all_public_access_blocks(self):
        with override_settings(AGENT_EVIDENCE_S3_BUCKET='public-media', AWS_STORAGE_BUCKET_NAME='public-media'):
            with self.assertRaises(EvidenceUnavailable):
                archive_store('s3')
        client = Mock()
        with override_settings(AGENT_EVIDENCE_S3_BUCKET='private-evidence', AWS_STORAGE_BUCKET_NAME='public-media'):
            with patch('boto3.client', return_value=client):
                store = archive_store('s3')
            client.get_public_access_block.return_value = {'PublicAccessBlockConfiguration': {}}
            with self.assertRaises(EvidenceUnavailable):
                store.put('v1/restaurant/object.jsonl.gz', b'evidence')
            client.put_object.assert_not_called()
            client.get_public_access_block.return_value = {'PublicAccessBlockConfiguration': {
                name: True for name in ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')
            }}
            store.put('v1/restaurant/object.jsonl.gz', b'evidence')
            kwargs = client.put_object.call_args.kwargs
            self.assertEqual(kwargs['IfNoneMatch'], '*')
            self.assertEqual(kwargs['ServerSideEncryption'], 'AES256')
            self.assertNotIn('ACL', kwargs)

    def test_scheduling_is_opt_in_for_allowlisted_restaurant_and_next_run_is_future(self):
        from django_q.models import Schedule
        self.assertFalse(Schedule.objects.filter(name='local-agents.evidence-retention').exists())
        call_command('agent_evidence_retention', restaurant=str(self.restaurant.pk), configure='schedule',
                     apply=True, stdout=io.StringIO())
        schedule = Schedule.objects.get(name='local-agents.evidence-retention')
        self.assertGreater(schedule.next_run, self.now)
        self.assertEqual(schedule.cron, '45 2 * * *')
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.schedule_enabled)

    def test_successful_historical_attempt_keeps_its_own_response(self):
        self.seed(inline=True)
        inbox = LocalAgentMutationInbox.objects.get()
        distinct = {'ok': True, 'status': 200, 'body': {'snapshot': 'different original ' * 150}}
        attempt = LocalAgentMutationAttempt.objects.create(inbox=inbox, payload_hash=inbox.payload_hash, result=distinct)
        LocalAgentMutationAttempt.objects.filter(pk=attempt.pk).update(created_at=self.old, updated_at=self.old)
        compact_operation(self.restaurant.pk, inbox.operation_id, self.now, dry_run=False)
        attempt.refresh_from_db()
        self.assertEqual(resolve_body(restaurant_id=self.restaurant.pk, operation_id=inbox.operation_id, body=attempt.result['body']), distinct['body'])
        self.assertEqual(AgentEvidencePayload.objects.count(), 2)
        report = self.archive()
        self.assertEqual(report['skips']['historical_attempt'], 1)

    def test_null_response_is_distinct_from_archived_content(self):
        self.assertIsNone(store_body(restaurant_id=self.restaurant.pk, operation_id='null-body', body=None))

    def test_version_two_envelope_and_certificate_survive_cold_replay(self):
        operation = {**self.operation, 'eventVersion': 2, 'ownerEpoch': 'original-owner', 'sequence': 1,
                     'dependsOn': [], 'fiscalSessionId': 'original-session'}
        first = self.seed(operation=operation)
        self.archive()
        result = receive_and_apply(agent=self.agent, operation=operation, apply=Mock(side_effect=AssertionError('duplicate')))
        self.assertEqual(result['body'], first['body'])
        inbox = LocalAgentMutationInbox.objects.get()
        self.assertEqual(inbox.owner_epoch, 'original-owner')
        self.assertEqual(inbox.last_result['dependencyPolicy'], 'order_isolation_v1')
        self.assertEqual(inbox.last_result['deferredOrderDependencies'], [])

    def test_compaction_keeps_cash_close_barrier_to_failed_payment_ancestor(self):
        from apps.local_agents.mutation_dependencies import unresolved_dependencies
        failed_order = uuid.uuid4()
        ancestor = {**self.operation, 'operationId': 'failed-payment-A', 'eventVersion': 2,
                    'ownerEpoch': 'owner', 'sequence': 1, 'dependsOn': [],
                    'path': f'/api/v1/pos/billing/orders/{failed_order}/pay/'}
        LocalAgentMutationInbox.objects.create(restaurant=self.restaurant, operation_id=ancestor['operationId'],
            operation=ancestor, payload_hash=_hash(ancestor), state='needs_review', event_version=2,
            owner_epoch='owner', sequence=1, depends_on=[])
        operation = {**self.operation, 'eventVersion': 2, 'ownerEpoch': 'owner', 'sequence': 2, 'dependsOn': [ancestor['operationId']]}
        self.seed(inline=True, operation=operation)
        compact_operation(self.restaurant.pk, operation['operationId'], self.now, dry_run=False)
        paid = LocalAgentMutationInbox.objects.get(operation_id=operation['operationId'])
        self.assertEqual(paid.last_result['deferredOrderDependencies'], [ancestor['operationId']])
        close_operation = {**operation, 'operationId': 'cash-close', 'sequence': 3,
                           'dependsOn': [operation['operationId']], 'path': '/api/v1/pos/billing/shifts/current/close/'}
        close = LocalAgentMutationInbox.objects.create(restaurant=self.restaurant, operation_id='cash-close',
            operation=close_operation, payload_hash=_hash(close_operation), event_version=2, owner_epoch='owner',
            sequence=3, depends_on=[paid.operation_id])
        missing, _ = unresolved_dependencies(close, close.depends_on)
        self.assertEqual(missing, [ancestor['operationId']])

    def test_maintenance_cursors_progress_and_cycle_past_unproven_payloads(self):
        self.seed(inline=True)
        # First compact candidate, then a second operation with the same age.
        extra = {**self.operation, 'operationId': 'next-operation'}
        self.seed(inline=True, operation=extra)
        first = run_retention(restaurant_id=self.restaurant.pk, apply=True, batch_size=1)
        second = run_retention(restaurant_id=self.restaurant.pk, apply=True, batch_size=1)
        self.assertEqual(first['rows'], 3)
        self.assertEqual(second['rows'], 3)
        self.assertEqual(AgentEvidencePayload.objects.count(), 2)

    def test_archive_cursor_progresses_past_a_full_batch_of_protected_resources(self):
        self.seed()
        for i in range(4):
            op_id = f'unproven-{i}'
            body = store_body(restaurant_id=self.restaurant.pk, operation_id=op_id, body={'large': 'x' * 1500})
            LocalAgentMutationReceipt.objects.create(restaurant=self.restaurant, operation_id=op_id,
                user_id=uuid.uuid4(), method='POST', path='/unproven/resource/', request_hash='a' * 64,
                response_status=200, response_body=body)
            LocalAgentMutationReceipt.objects.filter(operation_id=op_id).update(created_at=self.old, updated_at=self.old)
            AgentEvidencePayload.objects.filter(operation_id=op_id).update(created_at=self.old + timedelta(seconds=i))
        first = archive_payloads(self.restaurant.pk, self.now, 1, time.monotonic() + 30, dry_run=False)
        self.assertEqual(first['archived'], 0)
        self.assertEqual(first['skips']['unproven_resource'], 4)
        self.assertTrue(first['cursor'])
        second = archive_payloads(self.restaurant.pk, self.now, 1, time.monotonic() + 30, dry_run=False, cursor=first['cursor'])
        self.assertEqual(second['archived'], 1)

    def test_compaction_during_archive_upload_rechecks_changed_evidence(self):
        self.seed()
        original_put = FileArchiveStore.put

        def changed_put(store, key, data):
            original_put(store, key, data)
            LocalAgentMutationInbox.objects.filter(operation_id=self.operation['operationId']).update(updated_at=timezone.now())

        with patch.object(FileArchiveStore, 'put', changed_put):
            report = archive_payloads(self.restaurant.pk, self.now, 50, time.monotonic() + 30, dry_run=False)
        self.assertEqual(report['archived'], 0)
        self.assertEqual(report['changed_before_finalize'], 1)
        self.assertIsNotNone(AgentEvidencePayload.objects.get().content)

    def test_concurrent_replays_during_compaction_do_not_create_another_payment(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires independent PostgreSQL connections and row locks.')
        first = self.seed(inline=True)
        barrier = Barrier(3)

        def run(compact):
            try:
                agent = LocalAgent.objects.select_related('restaurant').get(pk=self.agent.pk)
                barrier.wait(timeout=10)
                if compact:
                    return compact_operation(agent.restaurant_id, self.operation['operationId'], self.now, dry_run=False)
                return receive_and_apply(agent=agent, operation=self.operation, apply=Mock(side_effect=AssertionError('duplicate')))
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(run, [False, True, False]))
        self.assertEqual(results[0]['body'], first['body'])
        self.assertEqual(results[2]['body'], first['body'])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(AgentEvidencePayload.objects.count(), 1)
