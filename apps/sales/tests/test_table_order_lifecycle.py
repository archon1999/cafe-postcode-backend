"""Acceptance for the table cancellation sequence that stalled LUMEN's Agent."""
import uuid
from unittest.mock import patch

from django.utils import timezone
from apps.billing.models import CashShift, Payment
from apps.floor.models import DiningTable, TableSession
from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class TableOrderLifecycleTests(PosAPITestCase):
    permission_codes = (*PosAPITestCase.permission_codes, 'pos_fiscal_receipts.skip')

    def test_reconnect_replays_cancel_new_session_and_payment_exactly_once(self):
        agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        operations = []

        def push(method, path, body):
            operation = {
                'operationId': 'lifecycle:' + str(uuid.uuid4()), 'userId': str(self.user.pk),
                'method': method, 'path': '/api/v1/pos/' + path, 'body': body,
                'eventVersion': 2, 'ownerEpoch': 'table-lifecycle', 'sequence': len(operations) + 1,
                'dependsOn': [operations[-1]['operationId']] if operations else [],
                'occurredAt': timezone.now().isoformat(),
            }
            response = self.client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            result = response.json()['results'][0]
            self.assertTrue(result['applied'], result)
            operations.append(operation)
            return result['body']

        with patch('apps.local_agents.mutations.authenticate_local_agent', return_value=agent):
            shift_id = str(uuid.uuid4())
            push('POST', 'billing/shifts/open/', {'cashDeskId': str(self.cash_desk.pk), 'edgeCashShiftId': shift_id, 'openingCashAmount': 0})
            old_session = push('POST', 'floor/table-sessions/', {'id': str(uuid.uuid4()), 'table': str(self.table.pk), 'guestCount': 2})
            old_order = push('POST', 'sales/orders/', {'id': str(uuid.uuid4()), 'tableSession': old_session['id']})
            old_item = push('POST', f"sales/orders/{old_order['id']}/items/", {'id': str(uuid.uuid4()), 'catalogItem': str(self.catalog_item.pk), 'quantity': 1})
            push('POST', f"sales/orders/{old_order['id']}/submit/", {})
            push('DELETE', f"sales/orders/items/{old_item['id']}/", {})
            historical_closed_at = TableSession.objects.get(pk=old_session['id']).closed_at
            new_session = push('POST', 'floor/table-sessions/', {'id': str(uuid.uuid4()), 'table': str(self.table.pk), 'guestCount': 2})
            new_order = push('POST', 'sales/orders/', {'id': str(uuid.uuid4()), 'tableSession': new_session['id']})
            push('POST', f"sales/orders/{new_order['id']}/items/", {'id': str(uuid.uuid4()), 'catalogItem': str(self.catalog_item.pk), 'quantity': 1})
            push('POST', f"sales/orders/{new_order['id']}/submit/", {})
            total = Order.objects.get(pk=new_order['id']).total
            payment_id = str(uuid.uuid4())
            shift = CashShift.objects.get(pk=shift_id, cash_desk=self.cash_desk, status='open')
            push('POST', f"billing/orders/{new_order['id']}/pay/", {
                'amount': total, 'cashAmount': total, 'cardAmount': 0, 'method': 'cash',
                'registerFiscal': False, 'edgePaymentId': payment_id, 'edgeCashShiftId': str(shift.pk),
            })
            replay = self.client.post('/api/v1/local-agent/sync/mutations/', {'operations': operations}, format='json')
            self.assertEqual(replay.status_code, 200, replay.data)
            self.assertTrue(all(r['applied'] and r['replayed'] for r in replay.json()['results']), replay.data)

        self.assertNotEqual(old_session['id'], new_session['id'])
        self.assertEqual(Order.objects.get(pk=old_order['id']).status, 'cancelled')
        self.assertEqual(Order.objects.get(pk=new_order['id']).status, 'closed')
        self.assertEqual(TableSession.objects.get(pk=old_session['id']).closed_at, historical_closed_at)
        self.assertEqual(TableSession.objects.get(pk=new_session['id']).status, 'closed')
        self.assertEqual(Payment.objects.filter(order_id=new_order['id']).count(), 1)
        self.assertEqual(Payment.objects.get(pk=payment_id).amount, total)
        self.assertEqual(LocalAgentMutationInbox.objects.filter(restaurant=self.restaurant, state='applied').count(), len(operations))
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)

    def test_last_submitted_item_closes_session_and_new_sitting_uses_new_identity(self):
        session = self.create_table_session()
        order = self.create_order_via_api({'table_session': str(session.pk)})
        item = self.add_item_via_api(order['id'])
        self.submit_order_via_api(order['id'])
        response = self.client.delete(f"/api/v1/pos/sales/orders/items/{item['id']}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['orderRemoved'])
        session.refresh_from_db()
        self.table.refresh_from_db()
        cancelled = Order.objects.get(pk=order['id'])
        self.assertEqual(cancelled.status, Order.Status.CANCELLED)
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(session.closed_at, cancelled.closed_at)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)

        rejected = self.client.post('/api/v1/pos/sales/orders/', {'table_session': str(session.pk)}, format='json')
        self.assertEqual(rejected.status_code, 400, rejected.data)
        opened = self.client.post('/api/v1/pos/floor/table-sessions/', {'table': str(self.table.pk), 'guest_count': 2}, format='json')
        self.assertEqual(opened.status_code, 201, opened.data)
        self.assertNotEqual(str(opened.data['id']), str(session.pk))
        successor = self.create_order_via_api({'table_session': str(opened.data['id'])})
        self.add_item_via_api(successor['id'])
        self.submit_order_via_api(successor['id'])
        session.refresh_from_db()
        self.assertEqual(session.status, TableSession.Status.CLOSED)
        self.assertEqual(session.closed_at, cancelled.closed_at)

    def test_removing_last_draft_item_keeps_the_sitting_open(self):
        session = self.create_table_session()
        order = self.create_order_via_api({'table_session': str(session.pk)})
        item = self.add_item_via_api(order['id'])
        response = self.client.delete(f"/api/v1/pos/sales/orders/items/{item['id']}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Order.objects.filter(pk=order['id']).exists())
        session.refresh_from_db()
        self.assertEqual(session.status, TableSession.Status.OPEN)
        self.assertIsNone(session.closed_at)
        self.create_order_via_api({'table_session': str(session.pk)})

    def test_merged_session_and_existing_active_order_are_rejected(self):
        session = self.create_table_session(status=TableSession.Status.MERGED)
        response = self.client.post('/api/v1/pos/sales/orders/', {'table_session': str(session.pk)}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        session.status = TableSession.Status.OPEN
        session.save(update_fields=['status'])
        first = self.create_order_via_api({'table_session': str(session.pk)})
        response = self.client.post('/api/v1/pos/sales/orders/', {'table_session': str(session.pk)}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(list(session.orders.values_list('id', flat=True)), [Order.objects.get(pk=first['id']).pk])
