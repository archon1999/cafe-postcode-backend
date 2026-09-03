from types import SimpleNamespace
from unittest.mock import call, patch

import httpx
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import FiscalShiftSession, Payment, Receipt
from apps.billing.services import CashShiftService, OrderPaymentService, PaymentFiscalRetryService
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.integrations.models import IntegrationConfig
from apps.integrations.services import get_fiscal_device_status
from apps.integrations.services.unikassa import UnikassaFiscalError, UnikassaFiscalIntegrationService
from apps.sales.models import Order
from apps.sales.models import OrderItem
from apps.sales.tests.support.pos_api import PosTestCase
from apps.users.models import Permission


class FiscalBusinessFlowTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.shift_service = CashShiftService()

    def create_closed_order(self, *, order_number=100):
        return Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=order_number,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=30000,
            closed_at=timezone.now(),
        )

    def create_success_payment(self, *, order, shift=None, amount=30000, register_fiscal=True):
        return Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=amount,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=register_fiscal,
            paid_at=timezone.now(),
        )

    def create_open_order_with_item(self, *, order_number=100):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=order_number,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        return order

    def test_cash_desk_bound_fiscal_session_is_visible_at_restaurant_scope(self):
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider="fiscal-drive-service",
            terminal_id="TERM-1",
            opened_at=timezone.now(),
        )

        self.assertTrue(
            self.shift_service.has_open_fiscal_shift(restaurant=self.restaurant)
        )
        self.assertTrue(
            self.shift_service.has_open_fiscal_shift(
                restaurant=self.restaurant, cash_desk=self.cash_desk
            )
        )

    def test_fiscal_sessions_are_isolated_per_cash_desk(self):
        second_cash_desk = self.restaurant.cash_desks.create(
            name="Second fiscal cashier",
            enabled_payment_methods=["cash", "card"],
        )
        first = FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider="fiscal-drive-service",
            terminal_id="TERM-1",
            opened_at=timezone.now(),
        )

        self.assertFalse(
            self.shift_service.has_open_fiscal_shift(
                restaurant=self.restaurant, cash_desk=second_cash_desk
            )
        )
        self.shift_service.open_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=second_cash_desk,
            opened_by=self.user,
            provider_result={
                "ok": True,
                "provider": "fiscal-drive-service",
                "terminal_id": "TERM-2",
            },
        )

        second = FiscalShiftSession.objects.get(cash_desk=second_cash_desk)
        self.shift_service.close_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=second_cash_desk,
            closed_by=self.user,
            provider_result={
                "ok": True,
                "provider": "fiscal-drive-service",
                "terminal_id": "TERM-2",
            },
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, FiscalShiftSession.Status.OPEN)
        self.assertEqual(second.status, FiscalShiftSession.Status.CLOSED)

    def test_trusted_duplicate_fiscal_open_is_idempotent_for_same_terminal(self):
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider="fiscal-drive-service",
            terminal_id="TERM-1",
            opened_at=timezone.now(),
        )
        provider_result = {
            "ok": True,
            "provider": "fiscal-drive-service",
            "terminal_id": "TERM-1",
        }

        result = self.shift_service.open_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            provider_result=provider_result,
        )

        self.assertTrue(result["already_open"])
        self.assertEqual(
            FiscalShiftSession.objects.filter(
                restaurant=self.restaurant,
                status=FiscalShiftSession.Status.OPEN,
            ).count(),
            1,
        )

    def test_trusted_fiscal_close_recovers_missing_open_session_audit(self):
        provider_result = {
            "ok": True,
            "provider": "fiscal-drive-service",
            "terminal_id": "TERM-1",
            "provider_report": {
                "z_info": {"TerminalID": "TERM-1", "TotalSaleCount": 1}
            },
        }

        result = self.shift_service.close_fiscal_shift(
            restaurant=self.restaurant,
            cash_desk=self.cash_desk,
            closed_by=self.user,
            provider_result=provider_result,
        )

        self.assertEqual(result["result"], provider_result)
        session = FiscalShiftSession.objects.get(restaurant=self.restaurant)
        self.assertEqual(session.status, FiscalShiftSession.Status.CLOSED)
        self.assertEqual(session.cash_desk, self.cash_desk)
        self.assertEqual(session.terminal_id, "TERM-1")
        self.assertTrue(session.open_payload["recovered_from_trusted_close"])

    def test_retry_partial_split_sends_only_failed_split_reason(self):
        order = self.create_closed_order()
        payment = self.create_success_payment(order=order)
        Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={'split_reason': 'mixed_cash_allowed_items', 'ok': True},
        )
        failed_receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.FAILED,
            payload={'split_reason': 'cash_forbidden_category', 'ok': False},
        )

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue:
            issue.return_value = [
                {
                    'ok': True,
                    'provider': 'unikassa',
                    'split_reason': 'cash_forbidden_category',
                    'fiscal_requested_at': timezone.now().isoformat(),
                    'fiscal_registered_at': timezone.now().isoformat(),
                }
            ]
            result = PaymentFiscalRetryService().retry(payment=payment)

        issue.assert_called_once_with(
            order=order,
            payment=payment,
            split_reasons=['cash_forbidden_category'],
        )
        failed_receipt.refresh_from_db()
        self.assertEqual(failed_receipt.status, Receipt.Status.SENT)
        self.assertEqual(len(result['receipts']), 1)

    def test_retry_failed_result_keeps_existing_receipt_unchanged(self):
        order = self.create_closed_order()
        payment = self.create_success_payment(order=order)
        failed_receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.FAILED,
            payload={'ok': False, 'detail': 'old error'},
            fiscal_error_code='OLD',
            fiscal_error_message='old error',
        )
        original_updated_at = failed_receipt.updated_at

        with patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue:
            issue.return_value = [
                {
                    'ok': False,
                    'provider': 'fiscal-drive-service',
                    'code': 'NEW',
                    'detail': 'new error',
                    'fiscal_requested_at': timezone.now().isoformat(),
                }
            ]
            result = PaymentFiscalRetryService().retry(payment=payment)

        failed_receipt.refresh_from_db()
        self.assertEqual(failed_receipt.status, Receipt.Status.FAILED)
        self.assertEqual(failed_receipt.payload, {'ok': False, 'detail': 'old error'})
        self.assertEqual(failed_receipt.fiscal_error_code, 'OLD')
        self.assertEqual(failed_receipt.fiscal_error_message, 'old error')
        self.assertEqual(failed_receipt.updated_at, original_updated_at)
        self.assertEqual(result['receipts'], [])
        self.assertEqual(result['result']['code'], 'NEW')

    def test_unikassa_split_issue_preserves_partial_success_result(self):
        order = self.create_closed_order()
        restricted_category = CatalogCategory.objects.create(
            restaurant=self.restaurant,
            name='Restricted',
            mxik_payload={'cashSale': 0},
        )
        restricted_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=restricted_category,
            name='Restricted item',
            price=10000,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            created_by=self.user,
            quantity=1,
            unit_price=20000,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=restricted_item,
            created_by=self.user,
            quantity=1,
            unit_price=10000,
        )
        order.recalculate_totals()
        payment = self.create_success_payment(order=order)
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )

        with (
            patch.object(service, '_client') as client_factory,
            patch.object(service, '_get_fiscal_memory_info', return_value=None),
            patch.object(service, '_send_receipt') as send_receipt,
        ):
            client_factory.return_value.__enter__.return_value = object()
            send_receipt.side_effect = [
                {
                    'ok': True,
                    'provider': 'unikassa',
                    'split_reason': 'mixed_cash_allowed_items',
                    'response': {'DateTime': timezone.now().isoformat()},
                },
                UnikassaFiscalError('second split failed', code='X1'),
            ]
            results = service.issue_receipts(order=order, payment=payment)

        self.assertEqual([result['split_reason'] for result in results], [
            'mixed_cash_allowed_items',
            'cash_forbidden_category',
        ])
        self.assertTrue(results[0]['ok'])
        self.assertFalse(results[1]['ok'])
        self.assertEqual(results[1]['code'], 'X1')

    def test_unikassa_mixed_payment_without_restricted_items_uses_single_breakdown_receipt(self):
        order = self.create_closed_order()
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            created_by=self.user,
            quantity=1,
            unit_price=10000,
        )
        order.recalculate_totals()
        payment = Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=order.total,
            cash_amount=6000,
            card_amount=5000,
            fiscal_cash_amount=6000,
            fiscal_card_amount=5000,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )

        parts = service._build_receipt_parts(order=order, payment=payment)
        receipt = service._build_sale_receipt(order=order, payment=payment, part=parts[0], memory_info=None)

        self.assertEqual(len(parts), 1)
        self.assertEqual(receipt['ReceivedCash'], 600000)
        self.assertEqual(receipt['ReceivedCard'], 500000)

    def test_unikassa_restricted_items_move_fiscal_cash_to_card(self):
        order = self.create_closed_order()
        restricted_category = CatalogCategory.objects.create(
            restaurant=self.restaurant,
            name='Cash forbidden',
            mxik_payload={'cashSale': 0},
        )
        restricted_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=restricted_category,
            name='Restricted item',
            price=5000,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            created_by=self.user,
            quantity=1,
            unit_price=5000,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=restricted_item,
            created_by=self.user,
            quantity=1,
            unit_price=5000,
        )
        order.recalculate_totals()
        payment = Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=order.total,
            cash_amount=6000,
            card_amount=4000,
            fiscal_cash_amount=5000,
            fiscal_card_amount=5000,
            fiscal_adjustment_reason='cash_forbidden_category',
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )

        parts = service._build_receipt_parts(order=order, payment=payment)
        normal_receipt = service._build_sale_receipt(order=order, payment=payment, part=parts[0], memory_info=None)
        restricted_receipt = service._build_sale_receipt(order=order, payment=payment, part=parts[1], memory_info=None)

        self.assertEqual([part.split_reason for part in parts], ['mixed_cash_allowed_items', 'cash_forbidden_category'])
        self.assertEqual(normal_receipt['ReceivedCash'], 500000)
        self.assertEqual(normal_receipt['ReceivedCard'], 0)
        self.assertEqual(restricted_receipt['ReceivedCash'], 0)
        self.assertEqual(restricted_receipt['ReceivedCard'], 500000)

    def test_unikassa_cash_sale_payload_restriction_prefers_item_payload(self):
        order = self.create_closed_order()
        category = CatalogCategory.objects.create(
            restaurant=self.restaurant,
            name='Restricted by category payload',
            mxik_payload={'cashSale': 0},
        )
        allowed_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=category,
            name='Allowed item override',
            price=30000,
            mxik_payload={'cashSale': 2},
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=allowed_item,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        payment = self.create_success_payment(order=order)
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )

        parts = service._build_receipt_parts(order=order, payment=payment)

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].pay_type, 'cash')
        self.assertEqual(parts[0].split_reason, 'none')

    def test_unikassa_sale_items_always_include_barcode_field(self):
        order = self.create_closed_order()
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        payment = self.create_success_payment(order=order)
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )

        part = service._build_receipt_parts(order=order, payment=payment)[0]
        receipt = service._build_sale_receipt(order=order, payment=payment, part=part, memory_info=None)

        self.assertIn('Barcode', receipt['Items'][0])
        self.assertEqual(receipt['Items'][0]['Barcode'], '')
        self.assertEqual(receipt['Items'][0]['Discount'], 0)
        self.assertEqual(receipt['Items'][0]['Other'], 0)
        self.assertEqual(receipt['Items'][0]['OwnerType'], 0)
        self.assertEqual(receipt['Items'][0]['PackageCode'], '')
        self.assertEqual(receipt['Items'][0]['Labels'], [])
        self.assertEqual(receipt['Items'][0]['VAT'], 321429)
        self.assertEqual(receipt['Items'][0]['VATPercent'], 12)
        self.assertEqual(receipt['Items'][0]['SPIC'], self.category.mxik_code)
        self.assertIsNone(receipt['RefundInfo'])
        self.assertEqual(receipt['ExtraInfo']['TIN'], self.restaurant.tax_number)
        self.assertEqual(receipt['ExtraInfo']['CarNumber'], '')
        self.assertEqual(receipt['ExtraInfo']['CardType'], 0)

    def test_unikassa_retries_once_after_datetime_sync_error(self):
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'})
        )
        client = object()
        with patch.object(service, '_post_json') as post_json:
            post_json.side_effect = [
                UnikassaFiscalError('DATETIME_SYNC_WITH_SERVER', code='9091'),
                {'OK': True},
                {'TerminalID': 'LG420', 'ReceiptSeq': 1},
            ]

            result = service._post_json_with_sync_retry(client, '/send/sale', {'Fiscal': 'LG420'})

        self.assertEqual(result['ReceiptSeq'], 1)
        self.assertEqual(
            post_json.call_args_list,
            [
                call(client, '/send/sale', {'Fiscal': 'LG420'}),
                call(client, '/get/sync', {'Fiscal': 'LG420', 'Number': None}),
                call(client, '/send/sale', {'Fiscal': 'LG420'}),
            ],
        )

    @patch('apps.integrations.services.unikassa.LocalAgentCommandService.local_http_request')
    def test_unikassa_default_transport_always_uses_local_agent(self, local_http_request):
        local_http_request.return_value = {
            'ok': True,
            'httpStatus': 200,
            'body': {'TerminalID': 'LG420'},
        }
        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(
                provider='unikassa',
                restaurant=self.restaurant,
                settings={
                    'endpoint_url': 'http://127.0.0.1:8181/api/v1',
                    'terminal_id': 'LG420',
                    'transport': 'direct',
                },
            )
        )

        result = service._post_json(object(), '/get/info', {'Fiscal': 'LG420', 'Number': None})

        self.assertEqual(result['TerminalID'], 'LG420')
        local_http_request.assert_called_once()
        self.assertEqual(local_http_request.call_args.kwargs['restaurant'], self.restaurant)
        self.assertEqual(local_http_request.call_args.kwargs['url'], 'http://127.0.0.1:8181/api/v1/get/info')

    @patch('apps.integrations.services.unikassa.LocalAgentCommandService.local_http_request')
    def test_unikassa_device_status_uses_agent_info(self, local_http_request):
        local_http_request.return_value = {
            'ok': True,
            'httpStatus': 200,
            'body': {'TerminalID': 'LG420'},
        }
        config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='unikassa',
            settings={'endpoint_url': 'http://127.0.0.1:8181/api/v1', 'terminal_id': 'LG420'},
        )
        self.cash_desk.fiscal_integration = config
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])

        status = get_fiscal_device_status(restaurant=self.restaurant, cash_desk=self.cash_desk)

        self.assertTrue(status['online'])
        self.assertEqual(status['provider'], 'unikassa')
        self.assertEqual(status['terminal_id'], 'LG420')
        local_http_request.assert_called_once()

    @patch('apps.integrations.services.unikassa.LocalAgentCommandService.local_http_request')
    def test_unikassa_device_status_offline_when_agent_info_fails(self, local_http_request):
        local_http_request.return_value = {
            'ok': True,
            'httpStatus': 503,
            'rawBody': 'Fiscal drive is unavailable',
        }
        config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='unikassa',
            settings={'endpoint_url': 'http://127.0.0.1:8181/api/v1', 'terminal_id': 'LG420'},
        )
        self.cash_desk.fiscal_integration = config
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])

        status = get_fiscal_device_status(restaurant=self.restaurant, cash_desk=self.cash_desk)

        self.assertFalse(status['online'])
        self.assertEqual(status['provider'], 'unikassa')
        self.assertIn('Fiscal drive is unavailable', status['detail'])

    @patch('apps.integrations.services.unikassa.LocalAgentCommandService.local_http_request')
    @patch('apps.integrations.services.unikassa.LocalAgentCommandService.execute')
    def test_unikassa_missing_endpoint_discovers_lan_endpoint(self, execute, local_http_request):
        execute.return_value = {
            'ok': True,
            'devices': [{'endpointUrl': 'http://192.168.0.177:8181/api/v1'}],
        }
        local_http_request.return_value = {
            'ok': True,
            'httpStatus': 200,
            'body': {'TerminalID': 'LG420'},
        }
        config = SimpleNamespace(provider='unikassa', restaurant=self.restaurant, settings={'terminal_id': 'LG420'})
        service = UnikassaFiscalIntegrationService(config)

        result = service._post_json(object(), '/get/info', {'Fiscal': 'LG420', 'Number': None})

        self.assertEqual(result['TerminalID'], 'LG420')
        execute.assert_called_once()
        self.assertEqual(execute.call_args.kwargs['command_type'], 'unikassa.discover')
        self.assertEqual(execute.call_args.kwargs['payload']['fiscal'], 'LG420')
        self.assertEqual(local_http_request.call_args.kwargs['url'], 'http://192.168.0.177:8181/api/v1/get/info')
        self.assertEqual(config.settings['endpoint_url'], 'http://192.168.0.177:8181/api/v1')

    def test_unikassa_injected_client_factory_keeps_unit_tests_direct(self):
        def client_factory(*args, **kwargs):
            return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'ok': True})))

        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'}),
            client_factory=client_factory,
        )

        self.assertFalse(service._use_local_agent())

    def test_unikassa_close_shift_collects_z_report_before_close(self):
        calls = []

        def handler(request: httpx.Request):
            path = request.url.path.removeprefix('/api/v1')
            calls.append(path)
            if path == '/get/z-info':
                return httpx.Response(
                    200,
                    json={
                        'TerminalID': 'LG420',
                        'OpenTime': '2026-05-20 09:00:00',
                        'TotalSaleCount': 2,
                        'TotalCash': {'Sale': 30000, 'Refund': 0},
                        'TotalCard': {'Sale': 0, 'Refund': 0},
                    },
                )
            if path == '/fiscal/close':
                return httpx.Response(200, text='OK')
            if path == '/get/fiscal-memory':
                return httpx.Response(200, json={'TerminalID': 'LG420', 'ZReportsCount': 4})
            return httpx.Response(404, json={'message': 'unexpected'})

        def client_factory(*args, **kwargs):
            return httpx.Client(transport=httpx.MockTransport(handler), base_url=kwargs['base_url'])

        service = UnikassaFiscalIntegrationService(
            SimpleNamespace(provider='unikassa', settings={'terminal_id': 'LG420'}),
            client_factory=client_factory,
        )

        result = service.close_shift()

        self.assertEqual(calls, ['/get/z-info', '/fiscal/close', '/get/fiscal-memory'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['provider_report']['z_info']['TotalSaleCount'], 2)
        self.assertEqual(result['provider_report']['fiscal_memory']['ZReportsCount'], 4)

    def test_cash_shift_close_blocks_unresolved_fiscal_payment(self):
        shift = self.create_cash_shift()
        order = self.create_closed_order()
        payment = self.create_success_payment(order=order, shift=shift)

        with self.assertRaises(ValidationError):
            self.shift_service.close_shift(
                shift=shift,
                actual_closing_cash_amount=30000,
                closed_by=self.user,
            )

        Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={'ok': True},
        )
        self.shift_service.close_shift(
            shift=shift,
            actual_closing_cash_amount=30000,
            closed_by=self.user,
        )
        shift.refresh_from_db()
        self.assertEqual(shift.status, shift.Status.CLOSED)
        self.assertEqual(shift.close_report_payload['report']['pos_report']['TotalSaleCount'], 1)

    def test_fiscal_shift_close_report_uses_session_period_across_shifts(self):
        first_shift = self.create_cash_shift()
        second_cash_desk = self.restaurant.cash_desks.create(
            name='Second cashier',
            enabled_payment_methods=['cash', 'card', 'qr'],
        )
        second_shift = self.create_cash_shift(cash_desk=second_cash_desk)
        first_order = self.create_closed_order(order_number=101)
        second_order = self.create_closed_order(order_number=102)
        first_payment = self.create_success_payment(order=first_order, shift=first_shift, amount=20000)
        second_payment = self.create_success_payment(
            order=second_order,
            shift=second_shift,
            amount=10000,
            register_fiscal=False,
        )
        Payment.objects.filter(pk=second_payment.pk).update(
            method=Payment.Method.CARD,
            cash_amount=0,
            card_amount=10000,
        )
        Receipt.objects.create(
            order=first_order,
            payment=first_payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={'ok': True},
        )

        with patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift:
            open_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            self.shift_service.open_fiscal_shift(restaurant=self.restaurant, opened_by=self.user)

        session = FiscalShiftSession.objects.get(restaurant=self.restaurant)
        first_payment.paid_at = session.opened_at
        first_payment.save(update_fields=['paid_at', 'updated_at'])
        second_payment.paid_at = session.opened_at
        second_payment.save(update_fields=['paid_at', 'updated_at'])

        with patch('apps.billing.services.cash_shift.close_fiscal_shift') as close_shift:
            close_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            payload = self.shift_service.close_fiscal_shift(restaurant=self.restaurant, closed_by=self.user)

        self.assertEqual(payload['report']['all']['count'], 2)
        self.assertEqual(payload['report']['all']['total'], 30000)
        self.assertEqual(payload['report']['fiscal_sent']['count'], 1)
        self.assertEqual(payload['report']['pos_report']['TotalSaleCount'], 2)
        self.assertEqual(payload['report']['pos_report']['TotalCash']['Sale'], 20000)
        self.assertEqual(payload['report']['pos_report']['TotalCash']['Precheck'], 0)
        self.assertEqual(payload['report']['pos_report']['TotalCash']['Receipt'], 20000)
        self.assertEqual(payload['report']['pos_report']['TotalCard']['Sale'], 10000)
        self.assertEqual(payload['report']['pos_report']['TotalCard']['Precheck'], 10000)
        self.assertEqual(payload['report']['pos_report']['TotalCard']['Receipt'], 0)
        self.assertEqual(payload['report']['fiscal_sent_report']['FiscalReceiptCount'], 1)
        session.refresh_from_db()
        self.assertEqual(session.status, FiscalShiftSession.Status.CLOSED)
        self.assertEqual(session.close_payload['reports']['pos_report']['TotalSaleCount'], 2)
        self.assertEqual(session.close_payload['provider_result']['response']['TerminalID'], 'LG420')

    def test_cash_shift_open_does_not_open_fiscal_shift(self):
        with patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift:
            open_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            self.shift_service.open_shift(
                restaurant=self.restaurant,
                cash_desk=self.cash_desk,
                opened_by=self.user,
                opening_cash_amount=100000,
            )

        open_shift.assert_not_called()
        self.assertFalse(FiscalShiftSession.objects.filter(restaurant=self.restaurant).exists())

    def test_first_fiscal_payment_auto_opens_fiscal_shift(self):
        shift = self.create_cash_shift()
        order = self.create_open_order_with_item(order_number=501)

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            open_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            issue.return_value = [
                {
                    'ok': True,
                    'provider': 'unikassa',
                    'receipt_number': '1001',
                    'fiscal_requested_at': timezone.now().isoformat(),
                    'fiscal_registered_at': timezone.now().isoformat(),
                }
            ]
            result = OrderPaymentService().process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total, 'register_fiscal': True},
                received_by=self.user,
                cash_shift=shift,
            )

        open_shift.assert_called_once_with(restaurant=self.restaurant, cash_desk=None)
        self.assertEqual(result['receipt'].status, Receipt.Status.SENT)
        session = FiscalShiftSession.objects.get(restaurant=self.restaurant)
        self.assertIsNone(session.cash_desk_id)
        self.assertEqual(session.status, FiscalShiftSession.Status.OPEN)

    def test_failed_fiscal_payment_becomes_precheck_and_does_not_block_shift_close(self):
        shift = self.create_cash_shift()
        order = self.create_open_order_with_item(order_number=511)
        self.restaurant.name = 'NYU YORK'
        self.restaurant.address = 'Beruniy'
        self.restaurant.phone = '+998901234567'
        self.restaurant.save(update_fields=['name', 'address', 'phone', 'updated_at'])

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            open_shift.return_value = {'ok': True, 'provider': 'unikassa'}
            issue.return_value = [
                {
                    'ok': False,
                    'provider': 'fiscal-drive-service',
                    'detail': 'Fiscal drive is locked.',
                }
            ]
            result = OrderPaymentService().process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total, 'register_fiscal': True},
                received_by=self.user,
                cash_shift=shift,
            )

        payment = result['payment']
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertFalse(payment.register_fiscal)
        self.assertEqual(
            payment.fiscal_adjustment_reason,
            'Fiscal registration failed; stored as precheck.',
        )
        self.assertEqual(result['receipt'].kind, Receipt.Kind.PLAIN)
        self.assertEqual(result['receipt'].status, Receipt.Status.CREATED)
        self.assertEqual(result['receipts'], [result['receipt']])
        self.assertIsNotNone(result['receipt'].print_document_id)
        self.assertFalse(Receipt.objects.filter(payment=payment, kind=Receipt.Kind.FISCAL).exists())
        self.shift_service.ensure_no_unresolved_fiscal_payments(shift=shift)

    def test_second_fiscal_payment_reuses_open_fiscal_shift(self):
        FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider='unikassa',
            terminal_id='LG420',
            opened_at=timezone.now(),
        )
        shift = self.create_cash_shift()
        order = self.create_open_order_with_item(order_number=502)

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            issue.return_value = [{'ok': True, 'provider': 'unikassa'}]
            OrderPaymentService().process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total, 'register_fiscal': True},
                received_by=self.user,
                cash_shift=shift,
            )

        open_shift.assert_not_called()

    def test_fiscal_skipped_payment_does_not_open_fiscal_shift(self):
        permission, _ = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'pos_fiscal_receipts.skip', 'description': 'Skip fiscal receipts'},
        )
        self.user.role.permissions.add(permission)
        self.tariff.permissions.add(permission)
        shift = self.create_cash_shift()
        order = self.create_open_order_with_item(order_number=503)

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            OrderPaymentService().process(
                order=order,
                payload={'method': Payment.Method.CASH, 'amount': order.total, 'register_fiscal': False},
                received_by=self.user,
                cash_shift=shift,
            )

        open_shift.assert_not_called()
        issue.assert_not_called()
        self.assertFalse(FiscalShiftSession.objects.filter(restaurant=self.restaurant).exists())

    def test_fiscal_retry_auto_opens_fiscal_shift(self):
        order = self.create_closed_order(order_number=504)
        payment = self.create_success_payment(order=order)

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            open_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            issue.return_value = [{'ok': True, 'provider': 'unikassa'}]
            PaymentFiscalRetryService().retry(payment=payment)

        open_shift.assert_called_once_with(restaurant=self.restaurant, cash_desk=None)
        self.assertTrue(FiscalShiftSession.objects.filter(restaurant=self.restaurant, status=FiscalShiftSession.Status.OPEN).exists())

    def test_fiscal_retry_converts_plain_payment_to_fiscal_payment(self):
        order = self.create_closed_order(order_number=505)
        payment = self.create_success_payment(order=order, register_fiscal=False)

        with (
            patch('apps.billing.services.cash_shift.open_fiscal_shift') as open_shift,
            patch('apps.billing.services.order_payment.issue_fiscal_receipts') as issue,
        ):
            open_shift.return_value = {'ok': True, 'provider': 'unikassa', 'response': {'TerminalID': 'LG420'}}
            issue.return_value = [
                {
                    'ok': True,
                    'provider': 'unikassa',
                    'receipt_number': '1002',
                    'fiscal_requested_at': timezone.now().isoformat(),
                    'fiscal_registered_at': timezone.now().isoformat(),
                }
            ]
            result = PaymentFiscalRetryService().retry(payment=payment)

        payment.refresh_from_db()
        self.assertTrue(payment.register_fiscal)
        self.assertEqual(result['receipt'].status, Receipt.Status.SENT)
        self.assertEqual(result['receipt'].payload['order_label'], '#505')
        self.assertEqual(result['receipt'].payload['cashier_name'], self.user.full_name)
        self.assertEqual(result['receipt'].payload['cashier_id'], str(self.user.id))
        self.assertIsNotNone(result['receipt'].print_document_id)

        result['receipt'].print_document = None
        result['receipt'].save(update_fields=['print_document', 'updated_at'])
        replayed = PaymentFiscalRetryService().retry(payment=payment)
        self.assertIsNotNone(replayed['receipt'].print_document_id)
