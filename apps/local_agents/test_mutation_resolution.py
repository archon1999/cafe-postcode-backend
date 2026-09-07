import copy
import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox, LocalAgentMutationAttempt
from apps.local_agents.mutation_inbox import receive_and_apply
from apps.local_agents.mutation_resolution import resolve_rejected_mutation
from apps.restaurants.models import Restaurant


class MutationResolutionTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Resolution QA')
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.op = {'operationId': 'pos:' + str(uuid.uuid4()), 'method': 'POST',
                   'path': '/api/v1/pos/billing/shifts/open/', 'userId': str(uuid.uuid4()),
                   'body': {'openingCashAmount': -1, 'edgeCashShiftId': str(uuid.uuid4())},
                   'occurredAt': timezone.now().isoformat(), 'ownerEpoch': 'test-owner', 'sequence': 1, 'eventVersion': 2}
        self.reject = lambda op: {'operationId': op['operationId'], 'ok': False, 'status': 400, 'body': {'openingCashAmount': ['min_value']}}
        receive_and_apply(agent=self.agent, operation=self.op, apply=self.reject)

    def test_resolution_unblocks_successor_preserves_rejection_and_is_idempotent(self):
        child = {**self.op, 'operationId': 'pos:' + str(uuid.uuid4()), 'sequence': 2,
                 'dependsOn': [self.op['operationId']], 'body': {'openingCashAmount': 0}}
        calls = []
        def apply(op):
            calls.append(op['operationId'])
            return {'ok': True, 'status': 201, 'operationId': op['operationId'], 'body': {}}
        blocked = receive_and_apply(agent=self.agent, operation=child, apply=apply)
        self.assertEqual(blocked['code'], 'MISSING_DEPENDENCIES')
        before = LocalAgentMutationInbox.objects.get(operation_id=self.op['operationId'])
        result = resolve_rejected_mutation(agent=self.agent, operation=self.op, reason='Empty rejected test cancelled')
        self.assertFalse(result['applied'])
        self.assertEqual(result['inboxState'], 'resolved')
        again = resolve_rejected_mutation(agent=self.agent, operation=self.op, reason='Retry lost acknowledgement')
        self.assertTrue(again['replayed'])
        replay = receive_and_apply(agent=self.agent, operation=self.op, apply=apply)
        self.assertEqual(replay['inboxState'], 'resolved')
        receive_and_apply(agent=self.agent, operation=child, apply=apply)
        receive_and_apply(agent=self.agent, operation=child, apply=apply)
        self.assertEqual(calls, [child['operationId']])
        after = LocalAgentMutationInbox.objects.get(pk=before.pk)
        self.assertEqual(after.operation, before.operation)
        self.assertEqual(after.payload_hash, before.payload_hash)
        self.assertIsNone(after.applied_at)
        self.assertEqual(after.attempts.count(), 2)
        self.assertEqual(after.attempts.get(result__has_key='previousResult').result['previousResult']['status'], 400)

    def test_wrong_payload_or_restaurant_cannot_cancel(self):
        changed = copy.deepcopy(self.op); changed['body']['openingCashAmount'] = 1
        other = Restaurant.objects.create(name='Other QA')
        other_agent, _ = LocalAgent.issue_for_restaurant(restaurant=other)
        for agent, op in [(self.agent, changed), (other_agent, self.op)]:
            with self.assertRaises(ValidationError):
                resolve_rejected_mutation(agent=agent, operation=op, reason='Cancel')

    def test_payment_or_unknown_evidence_is_not_cancellable(self):
        for path, status, retryable in [('/api/v1/pos/billing/orders/any/pay/', 400, False),
                                       ('/api/v1/pos/billing/shifts/open/', 503, True),
                                       ('/api/v1/pos/billing/shifts/current/close/', 400, False)]:
            op = {**self.op, 'operationId': str(uuid.uuid4()), 'sequence': None, 'eventVersion': 1, 'path': path}
            receive_and_apply(agent=self.agent, operation=op, apply=lambda _: {'ok': False, 'status': status, 'retryable': retryable})
            with self.assertRaises(ValidationError):
                resolve_rejected_mutation(agent=self.agent, operation=op, reason='Must not discard')
