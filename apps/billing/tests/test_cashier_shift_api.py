from unittest.mock import patch
import json
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from djangorestframework_camel_case.util import underscoreize
from apps.local_agents.models import LocalAgent
from apps.local_agents.tests_support import bind_agent_client
from apps.integrations.models import IntegrationConfig
from apps.billing.services import CashShiftService

from apps.billing.models import CashShift, FiscalShiftSession, Payment, PaymentRefund, Receipt
from apps.printing.models import PrintDocument
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class CashierShiftApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        agent, self.agent_token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.agent_client = APIClient()
        self.agent_identity = bind_agent_client(self.agent_client, agent, self.agent_token)
        fiscal = IntegrationConfig.objects.create(restaurant=self.restaurant, kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service', settings={'endpoint_url': 'http://127.0.0.1:3449'})
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration'])
        self.close_evidence = None
        self.browser_post = self.client.post
        self.client.post = self.post_with_shift_projection

    def post_with_shift_projection(self, path, data=None, **kwargs):
        if path not in ['/api/v1/pos/billing/shifts/open/', '/api/v1/pos/billing/shifts/current/close/']:
            return self.browser_post(path, data, **kwargs)
        body = dict(data or {})
        if path.endswith('/open/'):
            body['edge_cash_shift_id'] = str(uuid.uuid4())
        else:
            shift = CashShift.objects.get(cash_desk=self.cash_desk, status=CashShift.Status.OPEN)
            body['edge_cash_shift_id'] = str(shift.pk)
            if self.close_evidence is not None:
                body['edge_fiscal_result_json'] = json.dumps(self.close_evidence)
        return self.project_operation(path, body)

    def project_operation(self, path, body):
        operation = {'operationId': 'shift-test:' + str(uuid.uuid4()), 'userId': str(self.user.pk),
            'method': 'POST', 'path': path, 'body': body, 'occurredAt': timezone.now().isoformat()}
        response = self.agent_client.post('/api/v1/local-agent/sync/mutations/', {'operations':[operation]},
            format='json', HTTP_AUTHORIZATION=f'Bearer {self.agent_token}')
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data['results'][0]
        payload = underscoreize(result['body'])
        if 'print_documents' in payload:
            payload['printDocuments'] = payload.pop('print_documents')
        return Response(payload, status=result['status'])

    def test_last_shift_cannot_close_while_orders_are_open(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id)
        Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=991,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.SUBMITTED,
        )

        with self.assertRaises(ValidationError) as error:
            CashShiftService().ensure_shift_can_close(shift=CashShift.objects.get(cash_desk=self.cash_desk))
        self.assertEqual(error.exception.detail['code'], 'CASH_SHIFT_HAS_OPEN_ORDERS')
        self.assertEqual(int(error.exception.detail['openOrderCount']), 1)
        self.assertTrue(
            CashShift.objects.filter(cash_desk=self.cash_desk, status=CashShift.Status.OPEN).exists()
        )

    def test_cashier_context_returns_restaurant_fiscal_profile_and_cash_desks(self):
        response = self.client.get('/api/v1/pos/billing/context/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['restaurant_fiscal_profile']['legal_name'], self.branch.legal_name)
        self.assertEqual(response.data['restaurant_fiscal_profile']['tax_number'], self.branch.tax_number)
        self.assertTrue(response.data['restaurant_fiscal_profile']['service_fee_enabled'])
        self.assertEqual(response.data['restaurant_fiscal_profile']['service_fee_percent'], '10.00')
        self.assertEqual(len(response.data['available_cash_desks']), 1)
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration'])
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration_name'])
        self.assertIsNone(response.data['available_cash_desks'][0]['printer_integration_printer_name'])
        self.assertIsNone(response.data['current_shift'])
        self.assertFalse(response.data['fiscal_shift_open'])

    def test_cashier_context_detects_cash_desk_bound_fiscal_shift(self):
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='fiscal-drive-service',
            terminal_id='TERM-1',
            opened_at=timezone.now(),
        )

        response = self.client.get('/api/v1/pos/billing/context/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['fiscal_shift_open'])

    def test_open_and_close_shift_flow_returns_current_shift_summary(self):
        open_response = self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)

        current_shift = open_response['current_shift']
        self.assertIsNotNone(current_shift)
        self.assertEqual(str(current_shift['cash_desk']), str(self.cash_desk.id))
        self.assertEqual(current_shift['opening_cash_amount'], 150000)
        self.assertEqual(current_shift['expected_closing_cash_amount'], 150000)

        shift = CashShift.objects.get(pk=current_shift['id'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=77,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )

        context_response = self.client.get('/api/v1/pos/billing/context/')
        self.assertEqual(context_response.status_code, status.HTTP_200_OK, context_response.data)
        self.assertEqual(context_response.data['current_shift']['cash_total'], 40000)
        self.assertEqual(context_response.data['current_shift']['cash_precheck_total'], 40000)
        self.assertEqual(context_response.data['current_shift']['cash_receipt_total'], 0)
        self.assertEqual(context_response.data['current_shift']['card_precheck_total'], 0)
        self.assertEqual(context_response.data['current_shift']['card_receipt_total'], 0)
        self.assertEqual(context_response.data['current_shift']['expected_closing_cash_amount'], 190000)
        self.assertEqual(context_response.data['current_shift']['sale_count'], 1)
        self.assertEqual(context_response.data['current_shift']['refund_count'], 0)
        self.assertEqual(context_response.data['current_shift']['total_sale_amount'], 40000)
        self.assertEqual(context_response.data['current_shift']['cash_refund_total'], 0)
        self.assertEqual(context_response.data['current_shift']['card_refund_total'], 0)
        self.assertEqual(context_response.data['current_shift']['qr_refund_total'], 0)
        self.assertEqual(context_response.data['current_shift']['vat_sale_total'], 4286)
        self.assertEqual(context_response.data['current_shift']['vat_refund_total'], 0)
        self.assertEqual(context_response.data['current_shift']['first_receipt'], '77')
        self.assertEqual(context_response.data['current_shift']['last_receipt'], '77')

        close_response = self.close_shift_via_api(actual_closing_cash_amount=185000, notes_close='Cash mismatch')

        self.assertIsNone(close_response['current_shift'])
        self.assertEqual(len(close_response['printDocuments']), 1)
        shift.refresh_from_db()
        self.assertEqual(shift.status, CashShift.Status.CLOSED)
        self.assertEqual(shift.cash_difference_amount, -5000)

    def test_current_shift_summary_uses_mixed_payment_cash_breakdown(self):
        open_response = self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)
        shift = CashShift.objects.get(pk=open_response['current_shift']['id'])
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=78,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=33000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=33000,
            cash_amount=20000,
            card_amount=13000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )

        context_response = self.client.get('/api/v1/pos/billing/context/')

        self.assertEqual(context_response.status_code, status.HTTP_200_OK, context_response.data)
        self.assertEqual(context_response.data['current_shift']['cash_total'], 20000)
        self.assertEqual(context_response.data['current_shift']['card_total'], 13000)
        self.assertEqual(context_response.data['current_shift']['expected_closing_cash_amount'], 170000)

    def test_original_close_evidence_projects_both_shifts_without_device_rpc(self):
        self.close_evidence = {'ok': True, 'provider': 'fiscal-drive-service', 'response': {'TerminalID': 'LG420'}}
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='unikassa',
            terminal_id='LG420',
            opened_at=timezone.now(),
        )

        with patch('apps.billing.services.cash_shift.close_fiscal_shift') as close_fiscal:
            close_fiscal.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            response = self.client.post(
                '/api/v1/pos/billing/shifts/current/close/',
                {
                    'actual_closing_cash_amount': 150000,
                    'notes_close': '',
                    'close_fiscal_shift': False,
                },
                format='json',
            )

        close_fiscal.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn('fiscal_shift', response.data)
        self.assertEqual(len(response.data['printDocuments']), 1)
        document = PrintDocument.objects.get(pk=response.data['printDocuments'][0])
        self.assertEqual(document.metadata['reportType'], 'general')
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)
        session = FiscalShiftSession.objects.get(restaurant=self.restaurant)
        self.assertEqual(session.status, FiscalShiftSession.Status.CLOSED)

    def test_print_shift_report_returns_one_general_document_when_fiscal_shift_is_open(self):
        open_response = self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        shift_id = open_response['current_shift']['id']
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='fiscal-drive-service',
            terminal_id='TERM-1',
            opened_at=timezone.now(),
        )
        fiscal_report = {
            'TerminalID': 'TERM-1',
            'OpenTime': '2026-07-13 08:00:00',
            'CloseTime': '',
            'TotalSaleCount': 1,
            'TotalRefundCount': 0,
            'TotalCash': {'Sale': 50000, 'Refund': 0},
            'TotalCard': {'Sale': 0, 'Refund': 0},
            'TotalVAT': {'Sale': 5357, 'Refund': 0},
            'FirstReceiptSeq': 1,
            'LastReceiptSeq': 1,
        }

        with patch(
            'apps.billing.services.cash_shift.get_fiscal_shift_report',
            return_value=fiscal_report,
        ) as get_fiscal_report:
            response = self.client.post(
                '/api/v1/pos/billing/shifts/current/print-report/',
                {'cash_shift_id': shift_id},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data['printDocuments']), 1)
        document = PrintDocument.objects.get(pk=response.data['printDocuments'][0])
        self.assertEqual(document.metadata['reportType'], 'general')
        get_fiscal_report.assert_not_called()

    def test_close_cash_shift_skips_fiscal_close_when_fiscal_shift_was_not_opened(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=150000)

        with patch('apps.billing.services.cash_shift.close_fiscal_shift') as close_fiscal:
            response = self.client.post(
                '/api/v1/pos/billing/shifts/current/close/',
                {
                    'actual_closing_cash_amount': 150000,
                    'notes_close': '',
                    'close_fiscal_shift': True,
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        close_fiscal.assert_not_called()
        self.assertNotIn('fiscal_shift', response.data)
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)

    def test_close_fiscal_shift_with_unresolved_receipt_returns_clean_error(self):
        self.close_evidence = {'ok': True, 'provider': 'fiscal-drive-service', 'response': {'TerminalID': 'LG420'}}
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='unikassa',
            terminal_id='LG420',
            opened_at=timezone.now(),
        )
        shift = CashShift.objects.get(cash_desk=self.cash_desk, status=CashShift.Status.OPEN)
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=78,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=timezone.now(),
        )

        response = self.client.post(
            '/api/v1/pos/billing/shifts/current/close/',
            {'close_fiscal_shift': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Fiscalga yuborilmagan', response.data['detail'])
        self.assertIn('Local Agent', response.data['detail'])
        self.assertEqual(int(response.data['unresolved_fiscal_count']), 1)

    def test_fiscal_close_failure_keeps_pos_shift_open(self):
        self.close_evidence = {'ok': False, 'provider': 'fiscal-drive-service', 'detail': 'terminal offline'}
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='fiscal-drive-service',
            terminal_id='TERM-1',
            opened_at=timezone.now(),
        )

        with patch(
            'apps.billing.services.cash_shift.close_fiscal_shift',
            side_effect=RuntimeError('terminal offline'),
        ):
            response = self.client.post(
                '/api/v1/pos/billing/shifts/current/close/',
                {'close_fiscal_shift': False},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('edge_fiscal_result', response.data)
        self.assertTrue(
            CashShift.objects.filter(
                cash_desk=self.cash_desk, status=CashShift.Status.OPEN
            ).exists()
        )
        self.assertTrue(
            FiscalShiftSession.objects.filter(
                restaurant=self.restaurant, status=FiscalShiftSession.Status.OPEN
            ).exists()
        )

    def test_browser_retry_requires_owner_and_never_calls_fiscal_device(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=79,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        payment = Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=timezone.now(),
        )

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue_fiscal:
            issue_fiscal.return_value = [
                {
                    'ok': False,
                    'provider': 'unikassa',
                    'detail': 'Unikassa request failed: illegal request line',
                    'split_reason': 'none',
                }
            ]
            response = self.client.post(f'/api/v1/pos/billing/payments/{payment.id}/retry-fiscal/')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'FINANCIAL_OWNER_UPGRADE_REQUIRED')
        issue_fiscal.assert_not_called()

    def test_refund_and_print_document_endpoints_work_for_closed_paid_order(self):
        self.open_shift_via_api(cash_desk_id=self.cash_desk.id, opening_cash_amount=0)
        shift = CashShift.objects.get(cash_desk=self.cash_desk)
        order = Order.objects.create(restaurant=self.restaurant, distribution_point=self.takeaway_distribution,
            opened_by=self.user, cashier=self.user, order_number=79, channel='takeaway', status='closed', total=40000)
        payment = Payment.objects.create(order=order, cash_desk=self.cash_desk, cash_shift=shift,
            received_by=self.user, method='cash', amount=40000, status='succeeded', register_fiscal=False, paid_at=timezone.now())
        printed = self.client.post(f'/api/v1/pos/billing/payments/{payment.pk}/print-document/')
        self.assertEqual(printed.status_code, 200, printed.data)
        self.assertIsNotNone(printed.data['receipt']['print_document'])
        with patch('apps.billing.services.payment_refund.issue_refund_receipt') as device_refund:
            refunded = self.project_operation(f'/api/v1/pos/billing/{payment.pk}/refund/',
                {'reason':'Customer returned order', 'edge_cash_shift_id':str(shift.pk), 'edge_refund_result':{'ok':True}})
        self.assertEqual(refunded.status_code, 201, refunded.data)
        device_refund.assert_not_called()
        self.assertEqual(refunded.data['receipt']['kind'], Receipt.Kind.REFUND)
        self.assertIsNotNone(refunded.data['receipt']['print_document'])
        self.assertEqual(PaymentRefund.objects.filter(payment=payment, status='succeeded').count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)

