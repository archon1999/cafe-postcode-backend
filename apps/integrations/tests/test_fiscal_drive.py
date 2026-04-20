import json

import httpx

from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.integrations.models import IntegrationConfig
from apps.integrations.services import issue_fiscal_receipt
from apps.integrations.services.fiscal_drive import FiscalDriveIntegrationService
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase


class FiscalDriveIntegrationTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.cash_desk.terminal_id = 'TERM-1'
        self.cash_desk.external_cashbox_id = 'CASHBOX-1'
        self.cash_desk.save(update_fields=['terminal_id', 'external_cashbox_id', 'updated_at'])
        self.catalog_item.mxik_code = '10000000000000001'
        self.catalog_item.save(update_fields=['mxik_code', 'updated_at'])
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            order_number=25,
            channel=Order.Channel.HALL,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        self.order.recalculate_totals()
        self.payment = Payment.objects.create(
            order=self.order,
            cash_shift=self.create_cash_shift(),
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=self.order.total,
            status=Payment.Status.SUCCEEDED,
        )
        self.config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='soliq-ofd',
            mode=IntegrationConfig.Mode.LIVE,
            settings={
                'endpoint_url': 'http://127.0.0.1:3459',
                'terminal_id': 'TERM-1',
                'tax_number': self.restaurant.tax_number,
            },
        )

    def _build_transport(self, assertions: dict):
        def handler(request: httpx.Request):
            path = request.url.path
            method = request.method.upper()
            if method != 'POST':
                return httpx.Response(405, json={'message': 'Method Not Allowed'})

            if path == '/FiscalDrive/List':
                return httpx.Response(200, json=[{'FactoryID': 'FACTORY-1'}])
            if path == '/FiscalDrive/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'Locked': False,
                        'POSLocked': False,
                        'POSAuth': False,
                    },
                )
            if path == '/FiscalDrive/FiscalMemory/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'LastOperationTime': '2026-04-20 18:00:00',
                        'ZReportsCount': 0,
                        'ReceiptsCount': 0,
                    },
                )
            if path == '/FiscalDrive/ZReport/Open/FACTORY-1':
                assertions['z_report_open_called'] = True
                return httpx.Response(200, text='OK')
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                assertions['request_payload'] = json.loads(request.content.decode())
                return httpx.Response(200, json=41)
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                form = dict(httpx.QueryParams(request.content.decode()))
                assertions['register_form'] = form
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 71,
                        'DateTime': '2026-04-20 18:00:10',
                        'FiscalSign': '123456789012',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=71&c=20260420180010&s=123456789012',
                    },
                )
            if path == '/DataBase/Files/Sync/FullReceipts/FACTORY-1':
                return httpx.Response(200, json={'SuccessfulsCount': 1})
            return httpx.Response(404, json={'message': f'Unexpected path: {path}'})

        return httpx.MockTransport(handler)

    def test_issue_receipt_uses_live_fiscal_service_and_adds_service_fee_item(self):
        assertions = {}

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=self._build_transport(assertions), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['provider'], 'soliq-ofd')
        self.assertEqual(result['terminal_id'], 'TERM-1')
        self.assertEqual(result['cashbox_id'], 'CASHBOX-1')
        self.assertEqual(result['receipt_number'], '71')
        self.assertTrue(assertions.get('z_report_open_called'))
        self.assertEqual(assertions['register_form']['TXID'], '41')

        payload = result['request']['receipt']
        self.assertEqual(payload['ReceivedCash'], 3300000)
        self.assertEqual(payload['ReceivedCard'], 0)
        self.assertEqual(len(payload['Items']), 2)
        self.assertEqual(payload['Items'][0]['Price'], 3000000)
        self.assertEqual(payload['Items'][0]['SPIC'], self.catalog_item.mxik_code)
        self.assertEqual(payload['Items'][1], {'Name': 'Service fee', 'Amount': 1000, 'Price': 300000})

    def test_issue_receipt_falls_back_to_category_mxik_code(self):
        self.catalog_item.mxik_code = ''
        self.catalog_item.save(update_fields=['mxik_code', 'updated_at'])
        self.category.mxik_code = '20000000000000002'
        self.category.save(update_fields=['mxik_code', 'updated_at'])
        assertions = {}

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=self._build_transport(assertions), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        self.assertTrue(result['ok'])
        payload = result['request']['receipt']
        self.assertEqual(payload['Items'][0]['SPIC'], self.category.mxik_code)

    def test_issue_refund_receipt_uses_original_receipt_metadata(self):
        Receipt.objects.create(
            order=self.order,
            payment=self.payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            provider='soliq-ofd',
            payload={
                'request': {
                    'receipt': {
                        'Time': '2026-04-20 18:00:10',
                        'Type': 0,
                        'Operation': 0,
                        'ReceivedCash': 33000,
                        'ReceivedCard': 0,
                        'Items': [
                            {'Name': 'Osh', 'Amount': 1000, 'Price': 30000},
                            {'Name': 'Service fee', 'Amount': 1000, 'Price': 3000},
                        ],
                    }
                },
                'response': {
                    'TerminalID': 'TERM-1',
                    'ReceiptSeq': 71,
                    'DateTime': '2026-04-20 18:00:10',
                    'FiscalSign': '123456789012',
                },
            },
        )
        refund = PaymentRefund.objects.create(
            payment=self.payment,
            amount=self.payment.amount,
            reason='Customer cancelled',
            refunded_by=self.user,
            status=PaymentRefund.Status.SUCCEEDED,
        )
        assertions = {}

        def handler(request: httpx.Request):
            path = request.url.path
            if path == '/FiscalDrive/List':
                return httpx.Response(200, json=[{'FactoryID': 'FACTORY-1'}])
            if path == '/FiscalDrive/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={'TerminalID': 'TERM-1', 'Locked': False, 'POSLocked': False, 'POSAuth': False},
                )
            if path == '/FiscalDrive/FiscalMemory/Info/FACTORY-1':
                return httpx.Response(200, json={'LastOperationTime': '2026-04-20 18:10:00', 'ZReportsCount': 1})
            if path == '/FiscalDrive/ZReport/Info/FACTORY-1':
                return httpx.Response(200, json={'OpenTime': '2026-04-20 18:00:00'})
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                assertions['refund_payload'] = json.loads(request.content.decode())
                return httpx.Response(200, json=52)
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 72,
                        'DateTime': '2026-04-20 18:10:05',
                        'FiscalSign': '999999999999',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=72&c=20260420181005&s=999999999999',
                    },
                )
            if path == '/DataBase/Files/Sync/FullReceipts/FACTORY-1':
                return httpx.Response(200, json={'SuccessfulsCount': 1})
            return httpx.Response(404, json={'message': f'Unexpected path: {path}'})

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=httpx.MockTransport(handler), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_refund_receipt(order=self.order, payment=self.payment, refund=refund)

        self.assertTrue(result['ok'])
        self.assertEqual(result['receipt_number'], '72')
        self.assertEqual(result['refund_id'], str(refund.id))
        self.assertEqual(result['payment_id'], str(self.payment.id))
        self.assertEqual(result['response']['FiscalSign'], '999999999999')
        self.assertEqual(assertions['refund_payload']['Operation'], 1)
        self.assertEqual(assertions['refund_payload']['RefundInfo']['TerminalID'], 'TERM-1')
        self.assertEqual(assertions['refund_payload']['RefundInfo']['ReceiptSeq'], 71)
        self.assertEqual(assertions['refund_payload']['RefundInfo']['DateTime'], '20260420180010')

    def test_issue_receipt_syncs_state_and_retries_after_datetime_sync_error(self):
        assertions = {'get_txid_calls': 0, 'state_sync_calls': 0}

        def handler(request: httpx.Request):
            path = request.url.path
            if path == '/FiscalDrive/List':
                return httpx.Response(200, json=[{'FactoryID': 'FACTORY-1'}])
            if path == '/FiscalDrive/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={'TerminalID': 'TERM-1', 'Locked': False, 'POSLocked': False, 'POSAuth': False},
                )
            if path == '/FiscalDrive/FiscalMemory/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={'LastOperationTime': '2026-04-20 18:10:00', 'ZReportsCount': 1},
                )
            if path == '/FiscalDrive/ZReport/Info/FACTORY-1':
                return httpx.Response(200, json={'OpenTime': '2026-04-20 18:00:00'})
            if path == '/FiscalDrive/State/Sync/FACTORY-1':
                assertions['state_sync_calls'] += 1
                return httpx.Response(200, text='OK')
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                assertions['get_txid_calls'] += 1
                if assertions['get_txid_calls'] == 1:
                    return httpx.Response(400, json={'Reason': '9091 - DATETIME_SYNC_WITH_SERVER'})
                return httpx.Response(200, json=88)
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 89,
                        'DateTime': '2026-04-20 18:10:05',
                        'FiscalSign': '555555555555',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=89&c=20260420181005&s=555555555555',
                    },
                )
            if path == '/DataBase/Files/Sync/FullReceipts/FACTORY-1':
                return httpx.Response(200, json={'SuccessfulsCount': 1})
            return httpx.Response(404, json={'message': f'Unexpected path: {path}'})

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=httpx.MockTransport(handler), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['receipt_number'], '89')
        self.assertEqual(assertions['state_sync_calls'], 1)
        self.assertEqual(assertions['get_txid_calls'], 2)

    def test_service_selector_uses_live_provider_integration(self):
        result = issue_fiscal_receipt(self.order, self.payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['provider'], 'soliq-ofd')
        self.assertEqual(result['mode'], 'live')
