import copy
import uuid
from datetime import timedelta

from django.utils import timezone
from djangorestframework_camel_case.util import underscoreize
from rest_framework.exceptions import ValidationError

from apps.devices.models import SecurityEvent
from apps.floor.models import TableSession
from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox, LocalAgentMutationReceipt
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.local_agents.order_header_recovery import recover_order_header
from apps.local_agents.tests_support import bind_agent_client
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class OriginalOrderHeaderRecoveryTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        bind_agent_client(self.client, self.agent, self.token)
        now = timezone.now()
        self.session = TableSession.objects.create(
            restaurant=self.restaurant, hall=self.hall, table=self.table, opened_by=self.user,
            status=TableSession.Status.CLOSED, opened_at=now-timedelta(hours=3), closed_at=now-timedelta(hours=2),
        )
        self.operation = {'operationId': 'pos:' + str(uuid.uuid4()), 'method': 'POST',
                          'path': '/api/v1/pos/sales/orders/', 'userId': str(self.user.pk),
                          'occurredAt': (now-timedelta(hours=1)).isoformat(),
                          'body': {'id': str(uuid.uuid4()), 'tableSession': str(self.session.pk),
                                   'channel': 'hall', 'displayName': '39', 'note': 'Original'}}
        result = self.client.post('/api/v1/local-agent/sync/mutations/', {'operations': [self.operation]},
                                  format='json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['results'][0]['status'], 400, result.data)
        self.inbox = LocalAgentMutationInbox.objects.get(operation_id=self.operation['operationId'])

    def recover(self, **overrides):
        return recover_order_header(agent=self.agent, operation=underscoreize(self.operation),
                                    reason='Restore evidenced legacy header', **overrides)

    def test_signed_http_recovery_replay_preserves_history_and_does_not_touch_payments(self):
        from apps.billing.models import Payment, Receipt
        before = copy.deepcopy(self.inbox.operation), self.inbox.payload_hash, self.session.closed_at
        money = Payment.objects.count(), Receipt.objects.count()
        response = self.client.post('/api/v1/local-agent/sync/mutations/recover-order-header/',
                                    {'operation': self.operation, 'reason': 'Recover original order', 'requestId': str(uuid.uuid4())},
                                    format='json', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['applied'])
        order = Order.objects.get(pk=self.operation['body']['id'])
        self.assertEqual(order.created_at, self.inbox.occurred_at)
        self.assertEqual(order.display_name, '39')
        self.assertEqual(order.note, 'Original')
        self.assertEqual(order.opened_by_id, self.user.pk)
        self.session.refresh_from_db(); self.inbox.refresh_from_db()
        self.assertEqual((self.inbox.operation, self.inbox.payload_hash, self.session.closed_at), before)
        self.assertEqual(self.session.status, TableSession.Status.CLOSED)
        self.assertEqual((Payment.objects.count(), Receipt.objects.count()), money)
        self.assertTrue(self.recover()['replayed'])
        self.assertEqual(SecurityEvent.objects.filter(event_type='sync.order_header.recovered').count(), 1)
        event = SecurityEvent.objects.get(event_type='sync.order_header.recovered')
        self.assertEqual(event.metadata['originalBackendResult']['status'], 400)
        replay = LocalAgentMutationProcessor().process(agent=self.agent, operation=self.inbox.operation)
        self.assertTrue(replay['applied']); self.assertTrue(replay['replayed'])
        self.assertEqual(LocalAgentMutationReceipt.objects.filter(operation_id=self.inbox.operation_id).count(), 1)

    def test_changed_proof_other_restaurant_and_unsigned_request_are_rejected(self):
        changed = underscoreize(copy.deepcopy(self.operation)); changed['body']['note'] = 'Changed'
        with self.assertRaises(ValidationError):
            recover_order_header(agent=self.agent, operation=changed, reason='Wrong proof')
        from apps.restaurants.models import Restaurant
        other, _ = LocalAgent.issue_for_restaurant(restaurant=Restaurant.objects.create(name='Other'))
        with self.assertRaises(ValidationError):
            recover_order_header(agent=other, operation=underscoreize(self.operation), reason='Wrong restaurant')
        response = self.client.post('/api/v1/local-agent/sync/mutations/recover-order-header/',
                                    {'operation': self.operation, 'reason': 'Unsigned'}, format='json')
        self.assertIn(response.status_code, [401, 403])
        self.assertFalse(Order.objects.filter(pk=self.operation['body']['id']).exists())

    def test_merge_existing_order_wrong_rejection_and_inactive_user_are_not_repaired(self):
        for change in ['merged', 'order', 'wrong_error', 'inactive']:
            with self.subTest(change=change):
                from django.db import transaction
                with transaction.atomic():
                    if change == 'merged':
                        TableSession.objects.filter(pk=self.session.pk).update(status='merged')
                    elif change == 'order':
                        Order.objects.create(id=self.operation['body']['id'], restaurant=self.restaurant,
                                             order_number=999, channel='hall', table_session=self.session)
                    elif change == 'wrong_error':
                        LocalAgentMutationInbox.objects.filter(pk=self.inbox.pk).update(last_result={
                            'status': 400, 'ok': False, 'body': {'note': ['Different validation error']}})
                    else:
                        type(self.user).objects.filter(pk=self.user.pk).update(is_active=False)
                    with self.assertRaises(ValidationError):
                        self.recover()
                    self.assertFalse(SecurityEvent.objects.filter(event_type='sync.order_header.recovered').exists())
                    transaction.set_rollback(True)

    def test_unmet_original_dependency_rolls_back_header_receipt_counter_and_audit(self):
        from apps.local_agents.mutation_inbox import _hash
        operation = underscoreize(copy.deepcopy(self.operation))
        operation['depends_on'] = ['missing-original']
        LocalAgentMutationInbox.objects.filter(pk=self.inbox.pk).update(
            operation=operation, payload_hash=_hash(operation), depends_on=operation['depends_on'])
        self.restaurant.refresh_from_db(); counter = self.restaurant.last_order_number
        with self.assertRaises(ValidationError):
            recover_order_header(agent=self.agent, operation=operation, reason='Blocked by original dependency')
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.last_order_number, counter)
        self.assertFalse(Order.objects.filter(pk=self.operation['body']['id']).exists())
        self.assertFalse(LocalAgentMutationReceipt.objects.filter(operation_id=self.inbox.operation_id).exists())
        self.assertFalse(SecurityEvent.objects.filter(event_type='sync.order_header.recovered').exists())

    def test_empty_historical_fee_snapshot_does_not_adopt_current_prices(self):
        TableSession.objects.filter(pk=self.session.pk).update(service_fee_snapshot=[])
        self.recover()
        order = Order.objects.get(pk=self.operation['body']['id'])
        self.assertEqual(order.service_fee_snapshot, [])
        self.assertEqual(order.restaurant_service_fee_percent, 0)
