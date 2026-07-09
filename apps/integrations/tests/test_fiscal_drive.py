import json
from unittest.mock import patch

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
            provider='fiscal-drive-service',
            settings={
                'endpoint_url': 'http://127.0.0.1:3459',
                'terminal_id': 'TERM-1',
                'tax_number': self.restaurant.tax_number,
            },
        )
        self.cash_desk.fiscal_integration = self.config
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])

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
        self.assertEqual(result['provider'], 'fiscal-drive-service')
        self.assertEqual(result['terminal_id'], 'TERM-1')
        self.assertEqual(result['cashbox_id'], 'CASHBOX-1')
        self.assertEqual(result['receipt_number'], '71')
        self.assertEqual(result['restaurant_legal_name'], self.restaurant.legal_name or self.restaurant.name)
        self.assertEqual(result['restaurant_address'], self.restaurant.address)
        self.assertTrue(assertions.get('z_report_open_called'))
        self.assertEqual(assertions['register_form']['TXID'], '41')

        payload = result['request']['receipt']
        self.assertEqual(payload['ReceivedCash'], 3300000)
        self.assertEqual(payload['ReceivedCard'], 0)
        self.assertEqual(len(payload['Items']), 2)
        self.assertEqual(payload['Items'][0]['Price'], 3000000)
        self.assertEqual(payload['Items'][0]['SPIC'], self.catalog_item.mxik_code)
        self.assertEqual(payload['Items'][1], {'Name': 'Xizmat haqi', 'Amount': 1000, 'Price': 300000})

    def test_issue_receipt_includes_vat_without_changing_total(self):
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save(update_fields=['vat_enabled', 'vat_percent', 'updated_at'])
        assertions = {}

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=self._build_transport(assertions), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        payload = result['request']['receipt']
        self.assertEqual(payload['ReceivedCash'], 3300000)
        self.assertEqual(payload['Items'][0]['Price'], 3000000)
        self.assertEqual(payload['Items'][0]['VATPercent'], 12)
        self.assertEqual(payload['Items'][0]['VAT'], 321429)
        self.assertEqual(payload['Items'][1]['VATPercent'], 12)
        self.assertEqual(payload['Items'][1]['VAT'], 32143)

    def test_issue_receipt_uses_units_and_barcode_from_mxik_payload(self):
        self.catalog_item.mxik_payload = {
            'commonUnitCode': 715,
            'internationalCode': '6297000747705',
        }
        self.catalog_item.save(update_fields=['mxik_payload', 'updated_at'])
        assertions = {}

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=self._build_transport(assertions), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        item = result['request']['receipt']['Items'][0]
        self.assertEqual(item['Units'], 715)
        self.assertEqual(item['Barcode'], '6297000747705')

    def test_issue_receipt_accepts_txid_object_response(self):
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
                return httpx.Response(200, json={'LastOperationTime': '2026-04-20 18:00:00', 'ZReportsCount': 0})
            if path == '/FiscalDrive/ZReport/Open/FACTORY-1':
                return httpx.Response(200, text='OK')
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                return httpx.Response(200, json={'TXID': 42})
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                assertions['register_form'] = dict(httpx.QueryParams(request.content.decode()))
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 72,
                        'DateTime': '2026-04-20 18:00:10',
                        'FiscalSign': '123456789012',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=72',
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
        self.assertEqual(result['txid'], 42)
        self.assertEqual(assertions['register_form']['TXID'], '42')

    def test_issue_receipt_opens_z_report_and_retries_when_register_reports_not_opened(self):
        assertions = {'get_txid_calls': 0, 'register_calls': 0, 'open_calls': 0}

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
                    json={
                        'LastOperationTime': '2026-04-20 18:00:00',
                        'ZReportsCount': 1,
                        'ReceiptsCount': 0,
                    },
                )
            if path == '/FiscalDrive/ZReport/Info/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'FirstReceiptSeq': 0,
                        'LastReceiptSeq': 0,
                        'TotalSaleCount': 0,
                    },
                )
            if path == '/FiscalDrive/ZReport/Open/FACTORY-1':
                assertions['open_calls'] += 1
                return httpx.Response(200, text='OK')
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                assertions['get_txid_calls'] += 1
                return httpx.Response(200, json=40 + assertions['get_txid_calls'])
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                assertions['register_calls'] += 1
                if assertions['register_calls'] == 1:
                    return httpx.Response(500, json={'Reason': '9021 - ZREPORT_IS_NOT_OPENED'})
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 73,
                        'DateTime': '2026-04-20 18:00:20',
                        'FiscalSign': '222222222222',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=73',
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
        self.assertEqual(result['receipt_number'], '73')
        self.assertEqual(assertions['open_calls'], 1)
        self.assertEqual(assertions['get_txid_calls'], 2)
        self.assertEqual(assertions['register_calls'], 2)

    def test_issue_receipt_defaults_units_when_mxik_payload_has_no_unit_code(self):
        self.catalog_item.mxik_payload = {
            'unitCode': None,
            'commonUnitCode': None,
            'units': None,
            'internationalCode': '6297000747705',
        }
        self.catalog_item.save(update_fields=['mxik_payload', 'updated_at'])
        assertions = {}

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=self._build_transport(assertions), base_url=kwargs['base_url'])

        service = FiscalDriveIntegrationService(self.config, client_factory=client_factory)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        self.assertEqual(result['request']['receipt']['Items'][0]['Units'], 796)

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
            provider='fiscal-drive-service',
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
        assertions = {'get_txid_calls': 0, 'state_sync_calls': 0, 'request_times': []}

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
                last_operation_time = (
                    '2099-01-01 10:00:00'
                    if assertions['state_sync_calls']
                    else '2026-04-20 18:10:00'
                )
                return httpx.Response(
                    200,
                    json={'LastOperationTime': last_operation_time, 'ZReportsCount': 1},
                )
            if path == '/FiscalDrive/ZReport/Info/FACTORY-1':
                return httpx.Response(200, json={'OpenTime': '2026-04-20 18:00:00'})
            if path == '/FiscalDrive/State/Sync/FACTORY-1':
                assertions['state_sync_calls'] += 1
                return httpx.Response(200, text='OK')
            if path == '/FiscalDrive/Receipt/GetTXID/FACTORY-1':
                assertions['get_txid_calls'] += 1
                assertions['request_times'].append(json.loads(request.content.decode())['Time'])
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
        self.assertNotEqual(assertions['request_times'][0], assertions['request_times'][1])
        self.assertEqual(assertions['request_times'][1], '2099-01-01 10:00:01')

    def test_issue_receipt_retries_when_fiscal_reports_receipt_time_in_past(self):
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
                    return httpx.Response(400, json={'detail': 'receipt time is in the past'})
                return httpx.Response(200, json=90)
            if path == '/FiscalDrive/Receipt/RegisterTXID/FACTORY-1':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 91,
                        'DateTime': '2026-05-07 10:00:05',
                        'FiscalSign': '666666666666',
                        'QRCodeURL': 'https://ofd.soliq.uz/check?t=TERM-1&r=91&c=20260507100005&s=666666666666',
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
        self.assertEqual(result['receipt_number'], '91')
        self.assertEqual(assertions['state_sync_calls'], 1)
        self.assertEqual(assertions['get_txid_calls'], 2)

    def test_service_selector_uses_live_provider_integration(self):
        result = issue_fiscal_receipt(self.order, self.payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['provider'], 'fiscal-drive-service')

    @patch('apps.integrations.services.fiscal_drive.LocalAgentCommandService.local_http_request')
    def test_default_transport_uses_local_agent_with_json_and_form_payloads(self, local_http_request):
        assertions = {}

        def handler(*_args, **kwargs):
            url = kwargs['url']
            if url.endswith('/FiscalDrive/List'):
                return {'httpStatus': 200, 'body': [{'FactoryID': 'FACTORY-1'}]}
            if url.endswith('/FiscalDrive/Info/FACTORY-1'):
                return {
                    'httpStatus': 200,
                    'body': {
                        'TerminalID': 'TERM-1',
                        'Locked': False,
                        'POSLocked': False,
                        'POSAuth': False,
                    },
                }
            if url.endswith('/FiscalDrive/FiscalMemory/Info/FACTORY-1'):
                return {'httpStatus': 200, 'body': {'LastOperationTime': '2026-04-20 18:00:00', 'ZReportsCount': 0}}
            if url.endswith('/FiscalDrive/ZReport/Open/FACTORY-1'):
                assertions['open_form'] = kwargs['form_body']
                return {'httpStatus': 200, 'rawBody': 'OK'}
            if url.endswith('/FiscalDrive/Receipt/GetTXID/FACTORY-1'):
                assertions['receipt_json'] = kwargs['json_body']
                return {'httpStatus': 200, 'body': 41}
            if url.endswith('/FiscalDrive/Receipt/RegisterTXID/FACTORY-1'):
                assertions['register_form'] = kwargs['form_body']
                return {
                    'httpStatus': 200,
                    'body': {
                        'TerminalID': 'TERM-1',
                        'ReceiptSeq': 71,
                        'DateTime': '2026-04-20 18:00:10',
                        'FiscalSign': '123456789012',
                    },
                }
            if url.endswith('/DataBase/Files/Sync/FullReceipts/FACTORY-1'):
                assertions['sync_form'] = kwargs['form_body']
                return {'httpStatus': 200, 'body': {'SuccessfulsCount': 1}}
            return {'httpStatus': 404, 'body': {'message': f'Unexpected URL: {url}'}}

        local_http_request.side_effect = handler

        service = FiscalDriveIntegrationService(self.config)
        result = service.issue_receipt(order=self.order, payment=self.payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['provider'], 'fiscal-drive-service')
        self.assertEqual(assertions['receipt_json']['ReceivedCash'], 3300000)
        self.assertIn('DateTime', assertions['open_form'])
        self.assertEqual(assertions['register_form'], {'TXID': 41})
        self.assertEqual(assertions['sync_form'], {'ItemsCount': 32})
