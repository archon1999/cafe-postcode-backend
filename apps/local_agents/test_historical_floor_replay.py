import copy
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.billing.models import Payment, Receipt
from apps.devices.models import SecurityEvent
from apps.floor.models import DiningTable, TableSession
from apps.local_agents.models import LocalAgent, LocalAgentCommand, LocalAgentMutationInbox
from apps.local_agents.historical_floor_replay import project_historical_floor
from apps.local_agents.mutation_processor import LocalAgentMutationProcessor
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class HistoricalFloorReplayTests(PosAPITestCase):
    permission_codes = (*PosAPITestCase.permission_codes, 'pos_fiscal_receipts.skip')

    def setUp(self):
        super().setUp()
        self.restaurant.service_fee_enabled = False
        self.restaurant.save()
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.processor = LocalAgentMutationProcessor()
        self.start = timezone.now() - timedelta(days=3)
        self.shift = self.create_cash_shift()
        type(self.shift).objects.filter(pk=self.shift.pk).update(opened_at=self.start-timedelta(hours=1))
        self.sid, self.oid = str(uuid.uuid4()), str(uuid.uuid4())
        self.operations = self.history(self.sid, self.oid, self.table)
        self.live = self.create_table_session()
        DiningTable.objects.filter(pk=self.table.pk).update(status='occupied')

    def op(self, path, body, minute, method='POST'):
        return {'operationId': 'pos:' + str(uuid.uuid4()), 'userId': str(self.user.pk),
                'method': method, 'path': '/api/v1/pos/' + path, 'body': body,
                'occurredAt': (self.start+timedelta(minutes=minute)).isoformat()}

    def history(self, sid, oid, table, offset=0):
        return [
            self.op('floor/table-sessions/', {'id': sid, 'table': str(table.pk), 'guestCount': 4,
                'openedAt': (self.start+timedelta(minutes=offset)).isoformat(), 'serviceFeeSnapshot': []}, offset),
            self.op('sales/orders/', {'id': oid, 'tableSession': sid, 'channel': 'hall', 'displayName': '1082'}, offset+1),
            self.op(f'sales/orders/{oid}/items/', {'id': str(uuid.uuid4()), 'catalogItem': str(self.catalog_item.pk),
                'quantity': 1}, offset+2),
            self.op(f'billing/orders/{oid}/pay/', {'method': 'cash', 'amount': 30000, 'registerFiscal': False,
                'edgePaymentId': str(uuid.uuid4()), 'edgeCashShiftId': str(self.shift.pk)}, offset+30),
        ]

    def intake(self, operations=None):
        for operation in operations or self.operations:
            result = self.processor.process(agent=self.agent, operation=operation, receive_only=True)
            self.assertTrue(result['durablyReceived'], result)
            self.assertFalse(result['applied'], result)

    def project(self, dry_run=False):
        return project_historical_floor(agent=self.agent, operation_id=self.operations[0]['operationId'], dry_run=dry_run)

    def test_complete_history_preserves_live_floor_original_time_and_idempotency(self):
        failed = self.processor.process(agent=self.agent, operation=self.operations[0])
        self.assertEqual(failed['status'], 400)
        self.intake()
        before = list(DiningTable.objects.values()), list(TableSession.objects.filter(pk=self.live.pk).values())
        evidence = list(LocalAgentMutationInbox.objects.values_list('operation', 'payload_hash'))
        with patch('apps.local_agents.services.LocalAgentCommandService.execute') as command:
            result = self.project()
        self.assertTrue(result['applied'], result)
        command.assert_not_called()
        self.assertEqual(LocalAgentCommand.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)
        order = Order.objects.get(pk=self.oid)
        session = TableSession.objects.get(pk=self.sid)
        self.assertEqual(order.closed_at, self.start+timedelta(minutes=30))
        self.assertEqual(session.closed_at, order.closed_at)
        self.assertEqual(session.opened_at, self.start)
        self.assertEqual(order.display_name, '1082')
        self.assertEqual(before, (list(DiningTable.objects.values()), list(TableSession.objects.filter(pk=self.live.pk).values())))
        self.assertEqual(evidence, list(LocalAgentMutationInbox.objects.values_list('operation', 'payload_hash')))
        self.assertTrue(self.project()['replayed'])
        self.assertEqual(len(self.project()['operationIds']), len(self.operations))
        self.assertEqual(Payment.objects.count(), 1)

    def test_move_and_merge_preserve_original_sessions_and_future_occupancy(self):
        for mode in ['move', 'merge']:
            with self.subTest(mode=mode):
                from django.db import transaction
                with transaction.atomic():
                    table = DiningTable.objects.create(hall=self.hall, table_number=2, name='Destination', seat_count=8, status='occupied')
                    current = self.create_table_session(table=table)
                    operations = copy.deepcopy(self.operations)
                    target_sid, target_oid = str(uuid.uuid4()), str(uuid.uuid4())
                    body = {'targetTableId': str(table.pk), 'expectedTargetSessionIds': []}
                    if mode == 'merge':
                        target = self.history(target_sid, target_oid, table, offset=4)
                        operations.extend(target[:3])
                        body.update(targetSessionId=target_sid, expectedTargetSessionIds=[target_sid])
                        operations[-4]['path'] = f'/api/v1/pos/billing/orders/{target_oid}/pay/'
                        operations[-4]['body']['amount'] = 60000
                    operations.append(self.op(f'floor/table-sessions/{self.sid}/transfer/', body, 10))
                    self.intake(operations)
                    before = list(DiningTable.objects.values()), list(TableSession.objects.filter(pk__in=[self.live.pk,current.pk]).values())
                    result = self.project()
                    self.assertTrue(result['applied'], result)
                    session = TableSession.objects.get(pk=self.sid)
                    if mode == 'move':
                        self.assertEqual(session.table_id, table.pk)
                        self.assertEqual(session.status, 'closed')
                    else:
                        self.assertEqual(session.status, 'merged')
                        self.assertEqual(session.closed_at, self.start+timedelta(minutes=10))
                        target = TableSession.objects.get(pk=target_sid)
                        self.assertEqual(target.guest_count, 8)
                        self.assertEqual(target.status, 'closed')
                        self.assertEqual(Order.objects.get(pk=target_oid).total, 60000)
                    self.assertEqual(before, (list(DiningTable.objects.values()), list(TableSession.objects.filter(pk__in=[self.live.pk,current.pk]).values())))
                    transaction.set_rollback(True)

    def test_existing_fiscal_evidence_is_saved_without_new_device_or_print_commands(self):
        from apps.integrations.models import IntegrationConfig
        integration = IntegrationConfig.objects.create(restaurant=self.restaurant, name='Existing fiscal', kind='fiscal', provider='fiscal-drive-service')
        self.cash_desk.fiscal_integration = integration
        self.cash_desk.save()
        proof = {'ok': True, 'provider': 'fiscal-drive-service', 'terminalId': 'TEST-T1', 'receiptNumber': '2000',
                 'response': {'DateTime': '2026-10-18 12:00:00', 'ReceiptSeq': '2000', 'TerminalID': 'TEST-T1'},
                 'request': {'receipt': {'ReceivedCash': 3000000, 'ReceivedCard': 0}}}
        self.operations[-1]['body'].update(registerFiscal=True, edgeFiscalResults=[proof])
        self.intake()
        with patch('apps.local_agents.services.LocalAgentCommandService._enqueue_command', side_effect=AssertionError('new device command')):
            result = self.project()
        self.assertTrue(result['applied'], result)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.kind, 'fiscal')
        self.assertEqual(receipt.status, 'sent')
        self.assertEqual(receipt.payload['receipt_number'], '2000')
        from apps.kitchen.models import KitchenTicket
        self.assertFalse(KitchenTicket.objects.filter(print_document__isnull=False).exists())
        self.assertEqual(LocalAgentCommand.objects.count(), 0)

    def test_missing_fiscal_evidence_never_issues_a_new_receipt(self):
        self.operations[-1]['body']['registerFiscal'] = True
        self.intake()
        result = self.project()
        self.assertFalse(result['applied'], result)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Receipt.objects.count(), 0)

    def test_revoked_origin_device_and_unsupported_connected_operation_stop_projection(self):
        from apps.devices.models import Device
        device = Device.objects.create(restaurant=self.restaurant, type=Device.Type.POS_TERMINAL, status=Device.Status.ACTIVE, name='Origin', paired_at=timezone.now(), lease_expires_at=timezone.now()+timedelta(days=1))
        for operation in self.operations:
            operation['deviceId'] = str(device.pk)
        self.intake()
        Device.objects.filter(pk=device.pk).update(revoked_at=timezone.now())
        result = self.project()
        self.assertEqual(result['result']['code'], 'POS_DEVICE_INVALID')
        self.assertFalse(Order.objects.exists())
        self.intake([self.op(f'floor/table-sessions/{self.sid}/group/', {'tableIds': [str(self.table.pk)]}, 5)])
        self.assertEqual(self.project()['code'], 'HISTORY_UNSUPPORTED_OPERATION')

    def test_dry_run_and_incomplete_history_roll_back_every_projection(self):
        self.intake()
        self.assertTrue(self.project(dry_run=True)['ok'])
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(SecurityEvent.objects.count(), 0)
        LocalAgentMutationInbox.objects.filter(operation_id=self.operations[-1]['operationId']).delete()
        result = self.project()
        self.assertFalse(result['applied'], result)
        self.assertEqual(result['code'], 'HISTORY_DEPENDENCY_WAIT')
        self.assertFalse(TableSession.objects.filter(pk=self.sid).exists())

    def test_partial_payment_is_not_a_complete_history(self):
        self.operations[-1]['body']['amount'] = 10000
        self.intake()
        result = self.project()
        self.assertFalse(result['applied'], result)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_four_partial_payments_close_at_final_original_payment(self):
        self.operations.pop()
        for minute in [10, 20, 30, 40]:
            self.operations.append(self.op(f'billing/orders/{self.oid}/pay/', {
                'method': 'cash', 'amount': 7500, 'registerFiscal': False,
                'edgePaymentId': str(uuid.uuid4()), 'edgeCashShiftId': str(self.shift.pk)}, minute))
        self.intake()
        result = self.project()
        self.assertTrue(result['applied'], result)
        self.assertEqual(Payment.objects.count(), 4)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(Order.objects.get(pk=self.oid).closed_at, self.start+timedelta(minutes=40))

    def test_invalid_original_open_time_returns_review_instead_of_server_error(self):
        self.operations[0]['body']['openedAt'] = '2026-99-99'
        self.intake()
        self.assertEqual(self.project()['code'], 'HISTORY_OPEN_TIME_REQUIRED')
        self.assertFalse(Order.objects.exists())

    def test_signed_history_endpoint_defaults_to_dry_run_and_rejects_unsigned_request(self):
        from apps.local_agents.tests_support import bind_agent_client
        bind_agent_client(self.client, self.agent, 'local-fixture')
        self.intake()
        endpoint = '/api/v1/local-agent/sync/mutations/project-history/'
        payload = {'operationId': self.operations[0]['operationId']}
        response = self.client.post(endpoint, payload, format='json', HTTP_AUTHORIZATION='Bearer local-fixture')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['ok'], response.data)
        self.assertTrue(response.data['dryRun'])
        self.assertFalse(Order.objects.exists())
        response = self.client.post(endpoint, {**payload, 'dryRun': False}, format='json')
        self.assertIn(response.status_code, [401, 403])
        self.assertFalse(Order.objects.exists())

    def test_current_overlap_or_existing_cancelled_record_requires_review(self):
        self.intake()
        TableSession.objects.filter(pk=self.live.pk).update(opened_at=self.start)
        result = self.project()
        self.assertFalse(result['applied'], result)
        self.assertEqual(result['code'], 'HISTORY_OCCUPANCY_CONFLICT')
        self.assertFalse(Order.objects.exists())
        Order.objects.create(id=self.oid, restaurant=self.restaurant, order_number=1082, channel='hall', status='cancelled')
        result = self.project()
        self.assertEqual(result['code'], 'HISTORY_EXISTING_STATE_CONFLICT')
        self.assertEqual(Order.objects.get(pk=self.oid).status, 'cancelled')

    def test_live_capacity_validation_remains_and_missing_child_waits(self):
        result = self.processor.process(agent=self.agent, operation=self.operations[0])
        self.assertFalse(result['applied'], result)
        self.assertEqual(result['status'], 400)
        result = self.processor.process(agent=self.agent, operation=self.operations[1])
        self.assertFalse(result['applied'], result)
        self.assertEqual(result['code'], 'DEPENDENCY_WAIT')
        self.assertEqual(result['inboxState'], 'received')
        self.assertEqual(result['blockedBy'], [self.operations[0]['operationId']])

    def test_tampered_evidence_and_wrong_restaurant_never_project(self):
        self.intake()
        row = LocalAgentMutationInbox.objects.get(operation_id=self.operations[0]['operationId'])
        changed = copy.deepcopy(row.operation)
        changed['body']['guestCount'] = 1
        LocalAgentMutationInbox.objects.filter(pk=row.pk).update(operation=changed)
        self.assertEqual(self.project()['code'], 'HISTORY_EVIDENCE_CONFLICT')
        from apps.restaurants.models import Restaurant
        other, _ = LocalAgent.issue_for_restaurant(restaurant=Restaurant.objects.create(name='Other'))
        result = project_historical_floor(agent=other, operation_id=row.operation_id, dry_run=False)
        self.assertEqual(result['code'], 'HISTORY_ROOT_REQUIRED')
        self.assertFalse(Order.objects.exists())
