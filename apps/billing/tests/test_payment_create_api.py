import json
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework.response import Response
from apps.local_agents.models import LocalAgent
from apps.local_agents.tests_support import bind_agent_client

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.billing.models import CashShift, Payment, Receipt
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.printing.models import PrintTemplate
from apps.sales.models import Order, OrderItem
from apps.sales.serializers import OrderSerializer
from apps.sales.services import OrderSubmissionService
from apps.restaurants.models import CashDesk, DistributionPoint, PrepStation, Restaurant
from apps.platform.models import RestaurantEntitlement


class PaymentCreateApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Test restaurant',
            service_fee_enabled=True,
            service_fee_percent=10,
        )
        cls.branch = cls.restaurant
        cls.permission = Permission.objects.get_or_create(
            code='pos_payments.create',
            defaults={'name': 'POS payments create', 'description': 'POS payments create permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='payments-cashier',
            defaults={'name': 'Payments cashier', 'description': 'Payments cashier role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set([cls.permission])
        cls.entitlement.allowed_roles.set([cls.role])
        cls.user = User.objects.create_user(
            username='payments-cashier',
            password='secret123',
            full_name='Payments Cashier',
            restaurant=cls.restaurant,
            role=cls.role,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Asosiy',
            mxik_code='10000000000000001',
            mxik_name='Asosiy',
        )
        cls.prep_station = PrepStation.objects.create(
            restaurant=cls.restaurant,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        cls.item = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Osh',
            prep_station=cls.prep_station,
        )
        cls.distribution_point = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )
        cls.delivery_distribution_point = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Delivery',
            kind=DistributionPoint.Kind.DELIVERY,
        )
        cls.cash_desk = CashDesk.objects.create(
            restaurant=cls.restaurant,
            name='Main cashier',
            location='Front desk',
            enabled_payment_methods=['cash', 'card', 'mixed'],
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.agent, self.agent_token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.agent_client = APIClient()
        self.agent_identity = bind_agent_client(self.agent_client, self.agent, self.agent_token)
        fiscal = IntegrationConfig.objects.create(restaurant=self.restaurant, kind=IntegrationConfig.Kind.FISCAL, provider='fiscal-drive-service', settings={'endpoint_url': 'http://127.0.0.1:3449'})
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration'])
        self.project_provider_ok = True
        self.project_operations = {}

        self.cash_shift = CashShift.objects.create(
            cash_desk=self.cash_desk,
            opened_by=self.user,
            opened_at=timezone.now(),
            opening_cash_amount=0,
        )
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=1001,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        self.order.recalculate_totals()

    def project_payment(self, path, data, **kwargs):
        """Exercise signed Agent HTTP ingestion of immutable payment evidence."""
        from djangorestframework_camel_case.util import underscoreize
        body = underscoreize(dict(data))
        op_id = body.get('edge_operation_id') or 'test-payment:' + str(uuid4())
        if op_id not in self.project_operations:
            body['edge_operation_id'] = op_id
            body['edge_cash_shift_id'] = str(self.cash_shift.pk)
            order = Order.objects.get(pk=path.split('/orders/')[1].split('/')[0])
            amount = int(body.get('amount') or 0)
            method = body.get('method')
            cash = amount if method == 'cash' else int(body.get('cash_amount') or 0)
            card = amount if method == 'card' else int(body.get('card_amount') or 0)
            body['edge_provider_result'] = {'ok': self.project_provider_ok, 'provider': 'cash' if method == 'cash' else 'marta-softpos',
                'reference': 'trx-1', 'status': 'SUCCESS' if self.project_provider_ok else 'FAILED',
                'detail': '' if self.project_provider_ok else 'failed', 'cardAmount': card, 'edgeOperationId': op_id}
            if method == 'cash':
                body.pop('edge_provider_result')
            payments = list(order.payments.filter(status='succeeded'))
            if body.get('register_fiscal', True) and sum(p.amount for p in payments) + amount == int(body.get('final_total') or order.total):
                body['edge_fiscal_results_json'] = json.dumps([{'ok': True, 'provider': 'fiscal-drive-service',
                    'receipt_number': op_id, 'terminal_id': 'FIXTURE-TERMINAL',
                    'response': {'TerminalID': 'FIXTURE-TERMINAL', 'ReceiptSeq': op_id},
                    'request': {'receipt': {'ReceivedCash': (cash + sum(p.cash_amount for p in payments)) * 100,
                        'ReceivedCard': (card + sum(p.card_amount for p in payments)) * 100}}}])
            self.project_operations[op_id] = {'operationId': op_id, 'userId': str(self.user.pk), 'method': 'POST',
                'path': path, 'occurredAt': timezone.now().isoformat(), 'body': body}
        response = self.agent_client.post('/api/v1/local-agent/sync/mutations/',
            {'operations': [self.project_operations[op_id]]}, format='json', HTTP_AUTHORIZATION=f'Bearer {self.agent_token}')
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data['results'][0]
        # Keep the existing service/serializer response assertions in these projection tests.
        return Response(result['body'], status=result['status'])

    def create_delivery_order(self, *, delivery_details=True):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.delivery_distribution_point,
            opened_by=self.user,
            order_number=1002,
            channel=Order.Channel.DELIVERY,
            status=Order.Status.OPEN,
            guest_count=1,
            delivery_phone='90-123-45-67' if delivery_details else '',
            delivery_address='Chilonzor 12' if delivery_details else '',
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        return order

    def create_hourly_hall_order(self):
        self.restaurant.service_fee_mode = 'hourly'
        self.restaurant.service_fee_hourly_rate = 60_000
        self.restaurant.save(
            update_fields=['service_fee_mode', 'service_fee_hourly_rate', 'updated_at']
        )
        zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name=f'Hourly zone {uuid4()}',
        )
        hall = Hall.objects.create(zone_or_cabin=zone, name='Hourly hall')
        table = DiningTable.objects.create(
            hall=hall,
            name='Hourly table',
            table_number=99,
            seat_count=4,
        )
        opened_at = timezone.now() - timedelta(minutes=61)
        table_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=hall,
            table=table,
            opened_by=self.user,
            assigned_waiter=self.user,
            opened_at=opened_at,
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=table_session,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=2001,
            channel=Order.Channel.HALL,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=30_000,
        )
        order.recalculate_totals()
        return order

    def test_takeaway_order_does_not_apply_restaurant_service_fee(self):
        self.order.refresh_from_db()

        self.assertEqual(self.order.subtotal, 30000)
        self.assertEqual(self.order.total, 30000)
        self.assertEqual(self.order.calculated_total, 30000)

    def test_delivery_order_does_not_apply_restaurant_service_fee(self):
        order = self.create_delivery_order()

        self.assertEqual(order.subtotal, 30000)
        self.assertEqual(order.total, 30000)
        self.assertEqual(order.calculated_total, 30000)

    @patch('apps.billing.services.order_payment.charge_payment')
    def test_hourly_quote_validator_rejects_stale_quote_before_charge(self, charge_payment):
        from apps.billing.services.order_payment import OrderPaymentService, ServiceFeeQuoteStale
        order = self.create_hourly_hall_order()
        quote = dict(OrderSerializer(order).data['service_fee_quote'])
        quote['billable_minutes'] -= 1
        with self.assertRaises(ServiceFeeQuoteStale):
            OrderPaymentService._prepare_service_fee_quote(order=order, quote=quote, trusted_edge_replay=False)
        charge_payment.assert_not_called()
        order.refresh_from_db()
        self.assertIsNone(order.service_fee_frozen_at)

    @patch(
        'apps.billing.services.order_payment.charge_payment',
        return_value={'ok': False, 'provider': 'cash', 'detail': 'failed'},
    )
    def test_failed_hourly_payment_does_not_freeze_timer(self, _charge_payment):
        self.project_provider_ok = False
        order = self.create_hourly_hall_order()
        quote = OrderSerializer(order).data['service_fee_quote']

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 1_000,
                'serviceFeeQuote': quote,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        order.refresh_from_db()
        self.assertIsNone(order.service_fee_frozen_at)
        self.assertEqual(response.data['payment']['status'], Payment.Status.FAILED)

    @patch(
        'apps.billing.services.order_payment.charge_payment',
        return_value={'ok': True, 'provider': 'cash', 'reference': ''},
    )
    def test_first_successful_partial_hourly_payment_freezes_timer(self, _charge_payment):
        order = self.create_hourly_hall_order()
        quote = OrderSerializer(order).data['service_fee_quote']

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 1_000,
                'serviceFeeQuote': quote,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        order.refresh_from_db()
        self.assertIsNotNone(order.service_fee_frozen_at)
        frozen_amount = order.get_service_fee_amount()
        order.recalculate_totals(as_of=timezone.now() + timedelta(hours=5))
        self.assertEqual(order.get_service_fee_amount(), frozen_amount)

    @patch(
        'apps.billing.services.order_payment.charge_payment',
        return_value={'ok': True, 'provider': 'cash', 'reference': ''},
    )
    def test_cashier_editable_total_keeps_original_item_total(self, _charge_payment):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)
        self.restaurant.payment_total_mode = Restaurant.PaymentTotalMode.CASHIER_EDITABLE
        self.restaurant.save(update_fields=['payment_total_mode', 'updated_at'])

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 15000,
                'finalTotal': 15000,
                'register_fiscal': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.order.refresh_from_db()
        item = self.order.items.get()
        self.assertEqual(item.line_total, 30000)
        self.assertEqual(self.order.subtotal, 30000)
        self.assertEqual(self.order.calculated_total, 30000)
        self.assertEqual(self.order.total, 15000)
        self.assertEqual(self.order.total_override, 15000)
        self.assertEqual(self.order.total_override_reason, '')
        self.assertEqual(self.order.total_overridden_by_id, self.user.id)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(response.data['payment']['amount'], 15000)

    def test_fixed_total_mode_rejects_cashier_override(self):
        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 15000,
                'finalTotal': 15000,
                'totalOverrideReason': 'Chegirma',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('finalTotal', response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 30000)
        self.assertIsNone(self.order.total_override)

    def test_invalid_payment_does_not_persist_prepared_total_override(self):
        self.restaurant.payment_total_mode = Restaurant.PaymentTotalMode.CASHIER_EDITABLE
        self.restaurant.save(update_fields=["payment_total_mode", "updated_at"])
        self.cash_desk.enabled_payment_methods = [Payment.Method.CASH]
        self.cash_desk.save(update_fields=["enabled_payment_methods", "updated_at"])

        response = self.project_payment(
            f"/api/v1/pos/billing/orders/{self.order.id}/pay/",
            {
                "method": Payment.Method.CARD,
                "amount": 15000,
                "finalTotal": 15000,
                "totalOverrideReason": "Chegirma",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("method", response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 30000)
        self.assertIsNone(self.order.total_override)

    def test_rejects_qr_payment_method_for_new_pos_flow(self):
        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.QR, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('method', response.data)

    @patch('apps.integrations.services.agent_marta.LocalAgentCommandService.local_http_request')
    def test_mixed_payment_projects_original_tenders_without_second_terminal_charge(self, local_http_request):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        local_http_request.side_effect = [
            {
                'ok': True,
                'httpStatus': 200,
                'body': {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            },
            {
                'ok': True,
                'httpStatus': 200,
                'body': {
                    'ok': True,
                    'status': 'SUCCESS',
                    'requestId': 'request-mixed',
                    'params': {'trxId': 'trx-mixed', 'rrn': 'rrn-mixed'},
                },
            },
        ]

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.MIXED,
                'amount': self.order.total,
                'cash_amount': 20000,
                'card_amount': self.order.total - 20000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.method, Payment.Method.MIXED)
        self.assertEqual(payment.cash_amount, 20000)
        self.assertEqual(payment.card_amount, 10000)
        self.assertEqual(payment.fiscal_cash_amount, 20000)
        self.assertEqual(payment.fiscal_card_amount, 10000)
        local_http_request.assert_not_called()

    def test_mixed_payment_rejects_invalid_breakdown_sum(self):
        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.MIXED,
                'amount': self.order.total,
                'cash_amount': 20000,
                'card_amount': 12000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)

    def test_mixed_payment_requires_cash_and_card_enabled(self):
        self.cash_desk.enabled_payment_methods = ['cash', 'mixed']
        self.cash_desk.save(update_fields=['enabled_payment_methods', 'updated_at'])

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.MIXED,
                'amount': self.order.total,
                'cash_amount': 20000,
                'card_amount': self.order.total - 20000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('method', response.data)

    @patch('apps.billing.services.order_payment.issue_fiscal_receipts')
    @patch(
        'apps.billing.services.order_payment.charge_payment',
        return_value={'ok': True, 'provider': 'cash', 'reference': ''},
    )
    def test_cash_payment_auto_submits_and_closes_order(self, charge_payment, issue_fiscal_receipts):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(self.order.cashier_id, self.user.id)
        self.assertEqual(response.data['payment']['method'], Payment.Method.CASH)
        self.assertEqual(response.data['receipt']['kind'], Receipt.Kind.PLAIN)
        self.assertEqual(response.data['receipt']['status'], Receipt.Status.CREATED)
        self.assertIsNotNone(response.data['receipt']['printDocument'])
        payment = Payment.objects.get(order=self.order)
        self.assertFalse(payment.register_fiscal)
        receipt = payment.receipts.get()
        self.assertEqual(receipt.kind, Receipt.Kind.PLAIN)
        self.assertEqual(receipt.print_document.kind, PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN)
        self.assertEqual(receipt.print_document.template_version.status, 'published')
        charge_payment.assert_called_once()
        issue_fiscal_receipts.assert_not_called()

    def test_plain_receipt_includes_zone_for_a_multi_zone_hall_order(self):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)
        primary_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name='Asosiy zona',
            sort_order=1,
        )
        second_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name='VIP kabina',
            sort_order=2,
        )
        hall = Hall.objects.create(zone_or_cabin=primary_zone, name='Asosiy zal')
        Hall.objects.create(zone_or_cabin=second_zone, name='VIP zal')
        table = DiningTable.objects.create(
            hall=hall,
            zone=primary_zone,
            name='23-stol',
            table_number=23,
            seat_count=4,
        )
        table_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=hall,
            table=table,
            opened_by=self.user,
            guest_count=1,
        )
        self.order.table_session = table_session
        self.order.channel = Order.Channel.HALL
        self.order.save(update_fields=('table_session', 'channel', 'updated_at'))

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        snapshot = Receipt.objects.get(order=self.order).print_document.data_snapshot['order']
        self.assertEqual(snapshot['tableNumber'], 23)
        self.assertEqual(snapshot['zone'], 'Asosiy zona')
        self.assertEqual(snapshot['zoneDisplay'], 'Asosiy zona')

    def test_payment_returns_kitchen_document_for_configured_station_printer(self):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'connection_type': 'system_printer', 'printer_name': 'Kitchen Printer'},
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=['printer_integration', 'updated_at'])

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        ticket = KitchenTicket.objects.get(order=self.order, prep_station=self.prep_station)
        self.assertEqual(response.data['kitchenPrintDocuments'], [str(ticket.print_document_id)])

    def test_receipt_print_document_aggregates_duplicate_items(self):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=2,
            unit_price=30000,
        )
        self.order.recalculate_totals()

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(
            receipt.print_document.data_snapshot['items'],
            [
                {
                    'name': 'Osh',
                    'quantity': 3,
                    'unitPrice': 30000,
                    'lineTotal': 90000,
                    'note': '',
                    'modifierText': '',
                    'modifiers': [],
                    'vat': 9643,
                    'vatPercent': 12,
                }
            ],
        )

    def test_payment_does_not_return_already_submitted_kitchen_document(self):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'connection_type': 'system_printer', 'printer_name': 'Kitchen Printer'},
        )
        self.prep_station.printer_integration = printer
        self.prep_station.save(update_fields=['printer_integration', 'updated_at'])
        OrderSubmissionService().submit(self.order)
        existing_document_id = KitchenTicket.objects.get(order=self.order).print_document_id

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['kitchenPrintDocuments'], [])
        self.assertEqual(KitchenTicket.objects.get(order=self.order).print_document_id, existing_document_id)

    def test_edge_operation_id_makes_payment_replay_idempotent(self):
        payload = {
            'method': Payment.Method.CASH,
            'amount': self.order.total,
            'edgeOperationId': 'edge-payment-order-1001',
        }

        first = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            payload,
            format='json',
        )
        second = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            payload,
            format='json',
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.data['payment']['id'], second.data['payment']['id'])
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 1)

    @patch('apps.billing.services.order_payment.charge_payment')
    def test_public_pos_cannot_inject_edge_terminal_result(self, charge_payment):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {
                'method': Payment.Method.CARD,
                'amount': self.order.total,
                'edgeOperationId': 'edge-untrusted-card-1',
                'edgeProviderResult': {
                    'ok': True,
                    'provider': 'marta-softpos',
                    'status': 'SUCCESS',
                    'reference': 'trx-forged',
                    'cardAmount': self.order.total,
                    'edgeOperationId': 'edge-untrusted-card-1',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'FINANCIAL_OWNER_UPGRADE_REQUIRED')
        charge_payment.assert_not_called()
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    @patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': True, 'reference': 'split-ref'})
    def test_split_payments_can_close_order_across_multiple_methods(self, _charge_payment):
        first_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 20000, 'register_fiscal': True},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        first_payment = Payment.objects.get(order=self.order)
        self.assertEqual(first_payment.method, Payment.Method.CASH)
        self.assertEqual(first_payment.amount, 20000)
        self.assertEqual(first_payment.cash_amount, 20000)
        self.assertFalse(first_payment.register_fiscal)
        self.assertNotEqual(self.order.status, Order.Status.CLOSED)
        self.assertIsNone(first_response.data['receipt'])

        second_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': self.order.total - 20000, 'register_fiscal': True},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        payments = Payment.objects.filter(order=self.order, status=Payment.Status.SUCCEEDED).order_by('created_at')
        self.assertEqual(payments.count(), 2)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(sum(payment.amount for payment in payments), self.order.total)
        self.assertEqual(sum(payment.cash_amount for payment in payments), 20000)
        self.assertEqual(sum(payment.card_amount for payment in payments), self.order.total - 20000)

    @patch('apps.billing.services.order_payment.issue_fiscal_receipts')
    @patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': True, 'reference': 'plain-split-ref'})
    def test_plain_split_payments_can_partially_pay_order(self, charge_payment, issue_fiscal_receipts):
        skip_permission = Permission.objects.get_or_create(
            code='pos_fiscal_receipts.skip',
            defaults={'name': 'POS fiscal receipts skip', 'description': 'POS fiscal receipts skip permission'},
        )[0]
        self.role.permissions.add(skip_permission)
        self.entitlement.permissions.add(skip_permission)

        first_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 20000, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.CLOSED)
        self.assertIsNone(first_response.data['receipt'])

        second_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': self.order.total - 20000, 'register_fiscal': False},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        payments = Payment.objects.filter(order=self.order, status=Payment.Status.SUCCEEDED).order_by('created_at')
        self.assertEqual(payments.count(), 2)
        self.assertEqual(list(payments.values_list('method', flat=True)), [Payment.Method.CASH, Payment.Method.CARD])
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(receipt.kind, Receipt.Kind.PLAIN)
        self.assertEqual(receipt.payload['payment_method'], 'Aralash')
        self.assertEqual(receipt.payload['cash_amount'], 20000)
        self.assertEqual(receipt.payload['card_amount'], self.order.total - 20000)
        self.assertEqual(receipt.print_document.kind, PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN)
        self.assertEqual(receipt.print_document.data_snapshot['payment']['method'], 'Aralash')
        self.assertEqual(charge_payment.call_count, 1)
        issue_fiscal_receipts.assert_not_called()

    def test_closed_order_cannot_be_paid_twice(self):
        first_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total},
            format='json',
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)

        second_response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', second_response.data)

    def test_browser_payment_requires_financial_owner_before_creating_payment(self):
        response = self.client.post(f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': 'card', 'amount': self.order.total}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'FINANCIAL_OWNER_UPGRADE_REQUIRED')
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    @patch('apps.integrations.services.agent_marta.LocalAgentCommandService.local_http_request')
    def test_card_evidence_projects_original_reference_without_terminal_rpc(self, local_http_request):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        local_http_request.side_effect = [
            {
                'ok': True,
                'httpStatus': 200,
                'body': {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            },
            {
                'ok': True,
                'httpStatus': 200,
                'body': {
                    'ok': True,
                    'status': 'SUCCESS',
                    'requestId': 'request-1',
                    'params': {'trxId': 'trx-1', 'rrn': 'rrn-1'},
                },
            },
        ]

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_ref, 'trx-1')
        self.assertTrue(payment.provider_payload['trustedEdgeReplay'])
        local_http_request.assert_not_called()

    def test_browser_initiate_without_configuration_requires_owner(self):
        path = f'/api/v1/pos/billing/orders/{self.order.pk}/card-payments/initiate/'
        body = {'amount': self.order.total}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'FINANCIAL_AGENT_REQUIRED')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    def test_browser_initiate_with_configuration_cannot_create_payment(self):
        config = IntegrationConfig.objects.create(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos', settings={'endpoint_url': 'http://127.0.0.1:8090', 'hmac_secret': 'fixture-secret'})
        self.cash_desk.payment_integration = config
        self.cash_desk.save(update_fields=['payment_integration'])
        path = f'/api/v1/pos/billing/orders/{self.order.pk}/card-payments/initiate/'
        body = {'amount': self.order.total}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'FINANCIAL_AGENT_REQUIRED')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    def test_browser_terminal_success_cannot_complete_payment(self):
        config = IntegrationConfig.objects.create(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos', settings={'endpoint_url': 'http://127.0.0.1:8090', 'hmac_secret': 'fixture-secret'})
        self.cash_desk.payment_integration = config
        self.cash_desk.save(update_fields=['payment_integration'])
        payment = Payment.objects.create(order=self.order, amount=self.order.total, method='card', status='pending')
        path = f'/api/v1/pos/billing/payments/{payment.pk}/terminal-result/'
        body = {'ok': True, 'status': 'SUCCESS', 'params': {'trxId': 'untrusted'}}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'LEGACY_TERMINAL_EVIDENCE_REQUIRES_RECONCILIATION')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.external_ref, '')

    def test_browser_terminal_failure_cannot_mutate_payment(self):
        config = IntegrationConfig.objects.create(restaurant=self.restaurant, kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos', settings={'endpoint_url': 'http://127.0.0.1:8090', 'hmac_secret': 'fixture-secret'})
        self.cash_desk.payment_integration = config
        self.cash_desk.save(update_fields=['payment_integration'])
        payment = Payment.objects.create(order=self.order, amount=self.order.total, method='card', status='pending')
        path = f'/api/v1/pos/billing/payments/{payment.pk}/terminal-result/'
        body = {'ok': False, 'status': 'CANCELED', 'params': {'trxId': 'untrusted'}}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'LEGACY_TERMINAL_EVIDENCE_REQUIRES_RECONCILIATION')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.external_ref, '')

    def test_retired_initiate_does_not_route_to_kitchen(self):
        path = f'/api/v1/pos/billing/orders/{self.order.pk}/card-payments/initiate/'
        body = {'amount': self.order.total}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'FINANCIAL_AGENT_REQUIRED')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    def test_retired_terminal_result_does_not_route_to_kitchen(self):
        payment = Payment.objects.create(order=self.order, amount=self.order.total, method='card', status='pending')
        path = f'/api/v1/pos/billing/payments/{payment.pk}/terminal-result/'
        body = {'ok': False, 'status': 'CANCELED', 'params': {'trxId': 'untrusted'}}
        response = self.client.post(path, body, format='json')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'LEGACY_TERMINAL_EVIDENCE_REQUIRES_RECONCILIATION')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=self.order).exists())
        self.assertNotIn('marta', response.data)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.external_ref, '')

    @patch('apps.integrations.services.agent_marta.LocalAgentCommandService.local_http_request')
    def test_takeaway_card_payment_success_routes_to_kitchen_after_payment(self, local_http_request):
        order = self.order
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        local_http_request.side_effect = [
            {
                'ok': True,
                'httpStatus': 200,
                'body': {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            },
            {
                'ok': True,
                'httpStatus': 200,
                'body': {
                    'ok': True,
                    'status': 'SUCCESS',
                    'requestId': 'request-takeaway-success',
                    'params': {'trxId': 'trx-takeaway', 'rrn': 'rrn-takeaway'},
                },
            },
        ]

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(KitchenTicket.objects.filter(order=order, prep_station=self.prep_station).exists())

    def test_delivery_payment_rejects_missing_delivery_details(self):
        order = self.create_delivery_order(delivery_details=False)

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    def test_delivery_payment_rejects_invalid_delivery_phone(self):
        order = self.create_delivery_order()
        order.delivery_phone = '901234567'
        order.save(update_fields=['delivery_phone', 'updated_at'])

        response = self.project_payment(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    def test_browser_owner_gate_does_not_expose_foreign_resources(self):
        other_restaurant = Restaurant.objects.create(name='Foreign billing tenant')
        foreign_user = User.objects.create_user(
            username='foreign-billing-user',
            full_name='Foreign Billing User',
            restaurant=other_restaurant,
            role=self.role,
        )
        foreign_distribution = DistributionPoint.objects.create(
            restaurant=other_restaurant,
            name='Foreign takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )
        foreign_order = Order.objects.create(
            restaurant=other_restaurant,
            distribution_point=foreign_distribution,
            opened_by=foreign_user,
            order_number=9001,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        foreign_payment = Payment.objects.create(
            order=foreign_order,
            received_by=foreign_user,
            method=Payment.Method.CASH,
            amount=1000,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )

        foreign_payment_create_response = self.client.post(
            f'/api/v1/pos/billing/orders/{foreign_order.id}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 1000,
            },
            format='json',
        )
        unknown_payment_create_response = self.client.post(
            f'/api/v1/pos/billing/orders/{uuid4()}/pay/',
            {
                'method': Payment.Method.CASH,
                'amount': 1000,
            },
            format='json',
        )
        foreign_refund_response = self.client.post(
            f'/api/v1/pos/billing/{foreign_payment.id}/refund/',
            {'reason': 'Cross-tenant attempt'},
            format='json',
        )
        unknown_refund_response = self.client.post(
            f'/api/v1/pos/billing/{uuid4()}/refund/',
            {'reason': 'Unknown payment attempt'},
            format='json',
        )

        self.assertEqual(
            foreign_payment_create_response.status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(
            unknown_payment_create_response.status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(
            foreign_payment_create_response.data,
            unknown_payment_create_response.data,
        )
        self.assertEqual(
            foreign_refund_response.status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(
            unknown_refund_response.status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(foreign_refund_response.data, unknown_refund_response.data)

        foreign_order.refresh_from_db()
        foreign_payment.refresh_from_db()
        self.assertEqual(foreign_order.status, Order.Status.OPEN)
        self.assertEqual(foreign_payment.status, Payment.Status.SUCCEEDED)
        self.assertFalse(foreign_payment.refunds.exists())
        self.assertEqual(Payment.objects.filter(order=foreign_order).count(), 1)

