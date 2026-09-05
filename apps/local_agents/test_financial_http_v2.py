import json
import uuid
from unittest.mock import patch

from django.utils import timezone

from apps.billing.models import CashShift, Payment, FiscalShiftSession
from apps.billing.services import CashShiftService
from apps.integrations.models import IntegrationConfig
from apps.local_agents.models import LocalAgent, LocalAgentMutationInbox
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase


class FinancialEventHttpTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, _ = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        integration = IntegrationConfig.objects.create(restaurant=self.restaurant, name='HTTP fiscal',
            kind='fiscal', provider='fiscal-drive-service')
        self.cash_desk.fiscal_integration = integration
        self.cash_desk.save()
        self.auth_patch = patch('apps.local_agents.mutations.authenticate_local_agent', return_value=self.agent)
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def event(self, sequence, path, body, dependencies=None):
        return {'operationId': 'http:' + str(uuid.uuid4()), 'userId': str(self.user.pk),
            'method': 'POST', 'path': '/api/v1/pos/billing/' + path, 'body': body,
            'eventVersion': 2, 'ownerEpoch': 'http-owner', 'sequence': sequence,
            'dependsOn': dependencies or [], 'fiscalSessionId': 'http-fiscal-session',
            'occurredAt': timezone.now().isoformat()}

    def push(self, operation):
        response = self.client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()['results'][0]

    def test_camel_case_http_preserves_epoch_dependencies_and_fiscal_session(self):
        shift_id = str(uuid.uuid4())
        opening = self.event(1, 'shifts/open/', {'cashDeskId': str(self.cash_desk.pk),
            'edgeCashShiftId': shift_id, 'openingCashAmount': 0})
        fiscal = self.event(2, 'fiscal-shifts/open/', {'cashDeskId': str(self.cash_desk.pk),
            'edgeFiscalResultJson': json.dumps({'ok': True, 'provider': 'fiscal-drive-service', 'terminal_id': 'T-HTTP'})},
            [opening['operationId']])
        waiting = self.push(fiscal)
        self.assertFalse(waiting['applied'], waiting)
        self.assertEqual(waiting['missingDependencies'], [opening['operationId']])
        self.assertTrue(self.push(opening)['applied'])
        self.assertTrue(self.push(fiscal)['applied'])
        row = LocalAgentMutationInbox.objects.get(operation_id=fiscal['operationId'])
        self.assertEqual(row.owner_epoch, 'http-owner')
        self.assertEqual(row.event_version, 2)
        self.assertEqual(row.depends_on, [opening['operationId']])
        self.assertEqual(FiscalShiftSession.objects.get().edge_session_id, 'http-fiscal-session')
        self.assertTrue(CashShift.objects.filter(pk=shift_id).exists())
        self.assertEqual(CashShift.objects.get(pk=shift_id).cashier_id, self.user.pk)
        replay = self.push({**opening, 'attempts': 5})
        self.assertTrue(replay['applied'], replay)
        self.assertTrue(replay['replayed'])

    def test_camel_case_http_payment_retains_owner_id(self):
        shift = self.create_cash_shift()
        order = Order.objects.create(restaurant=self.restaurant, opened_by=self.user,
            distribution_point=self.takeaway_distribution, channel='takeaway', order_number=880)
        OrderItem.objects.create(order=order, catalog_item=self.catalog_item, prep_station=self.prep_station,
            created_by=self.user, quantity=1, unit_price=30000)
        order.recalculate_totals()
        payment_id = str(uuid.uuid4())
        evidence = {'ok': True, 'provider': 'fiscal-drive-service', 'terminal_id': 'T-HTTP', 'receipt_number': '42',
                    'response': {'DateTime': '2026-09-05 02:00:00'}, 'request': {'receipt': {'ReceivedCash': 3000000}}}
        operation = self.event(1, f'orders/{order.pk}/pay/', {'amount': 30000, 'method': 'cash',
            'edgeCashShiftId': str(shift.pk), 'edgePaymentId': payment_id, 'registerFiscal': True,
            'edgeFiscalResultsJson': json.dumps([evidence])})
        with patch('apps.billing.services.fiscal_evidence.attach_receipt_print_document'):
            result = self.push(operation)
        self.assertTrue(result['applied'], result)
        self.assertEqual(str(Payment.objects.get().pk), payment_id)
        from apps.local_agents.sync import _cash_shift_snapshot
        bootstrap_shift = next(row for row in _cash_shift_snapshot(self.restaurant) if row['id'] == str(shift.pk))
        self.assertEqual(bootstrap_shift['fiscalReceiptCount'], 1)
        order.refresh_from_db()
        label = {'operationId': 'label:' + str(uuid.uuid4()), 'userId': str(self.user.pk),
                 'method': 'PATCH', 'path': f'/api/v1/pos/sales/orders/{order.pk}/',
                 'body': {'displayName': order.display_name}}
        self.assertTrue(self.push(label)['applied'])
        changed = {**label, 'operationId': 'label-change:' + str(uuid.uuid4()), 'body': {'displayName': 'changed'}}
        self.assertFalse(self.push(changed)['applied'])

    def test_split_cash_then_card_aggregate_receipt_covers_both_tenders(self):
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save(update_fields=['vat_enabled', 'vat_percent'])
        shift = self.create_cash_shift()
        order = Order.objects.create(restaurant=self.restaurant, opened_by=self.user,
            distribution_point=self.takeaway_distribution, channel='takeaway', order_number=881)
        OrderItem.objects.create(order=order, catalog_item=self.catalog_item, prep_station=self.prep_station,
            created_by=self.user, quantity=1, unit_price=30000)
        order.recalculate_totals()
        first = self.event(1, f'orders/{order.pk}/pay/', {'amount': 15000, 'method': 'cash',
            'edgeCashShiftId': str(shift.pk), 'edgePaymentId': str(uuid.uuid4()), 'registerFiscal': True,
            'edgeFiscalResultsJson': '[]'})
        self.assertTrue(self.push(first)['applied'])
        self.assertFalse(order.receipts.exists())
        self.assertEqual(Payment.objects.get().status, 'succeeded')
        evidence = {'ok': True, 'provider': 'fiscal-drive-service', 'terminal_id': 'T-HTTP', 'receipt_number': '43',
                    'response': {'DateTime': '2026-09-05 02:00:01'},
                    'request': {'receipt': {'ReceivedCash': 1500000, 'ReceivedCard': 1500000}}}
        final = self.event(2, f'orders/{order.pk}/pay/', {'amount': 15000, 'method': 'card',
            'edgeCashShiftId': str(shift.pk), 'edgePaymentId': str(uuid.uuid4()), 'registerFiscal': True,
            'edgeFiscalResultsJson': json.dumps([evidence])}, [first['operationId']])
        final['body']['edgeProviderResult'] = {'ok': True, 'provider': 'marta-softpos', 'status': 'SUCCESS',
            'reference': 'split-card-test', 'cardAmount': 15000, 'edgeOperationId': final['operationId']}
        with patch('apps.billing.services.fiscal_evidence.attach_receipt_print_document'):
            result = self.push(final)
        self.assertTrue(result['applied'], result)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(order.receipts.count(), 1)
        from apps.local_agents.sync import _cash_shift_snapshot
        snapshot = next(row for row in _cash_shift_snapshot(self.restaurant) if row['id'] == str(shift.pk))
        for key, expected in {'cashReceiptTotal': 15000, 'cardReceiptTotal': 15000,
                              'cashPrecheckTotal': 0, 'cardPrecheckTotal': 0,
                              'fiscalReceiptCount': 1, 'saleCount': 2, 'vatSaleTotal': 3214}.items():
            self.assertEqual(snapshot[key], expected, key)
        report = CashShiftService().build_fiscal_shift_report(shift=shift)
        for name in ['pos_report', 'fiscal_sent_report']:
            self.assertEqual(report[name]['TotalCash']['Receipt'], 15000)
            self.assertEqual(report[name]['TotalCard']['Receipt'], 15000)
            self.assertEqual(report[name]['TotalCash']['Precheck'], 0)
            self.assertEqual(report[name]['FiscalReceiptCount'], 1)
            self.assertEqual(report[name]['TotalSaleCount'], 2)
            self.assertEqual(report[name]['TotalVAT']['Sale'], 3214)
