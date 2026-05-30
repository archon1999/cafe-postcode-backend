from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.billing.models import CashShift, Payment
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order, OrderItem
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
            enabled_payment_methods=['cash', 'card', 'qr'],
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
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

    def create_delivery_order(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.delivery_distribution_point,
            opened_by=self.user,
            order_number=1002,
            channel=Order.Channel.DELIVERY,
            status=Order.Status.OPEN,
            guest_count=1,
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

    def test_takeaway_order_applies_service_fee_when_enabled(self):
        self.order.refresh_from_db()

        self.assertEqual(self.order.subtotal, 30000)
        self.assertEqual(self.order.total, 33000)

    def test_rejects_mixed_payment_method(self):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.MIXED, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('method', response.data)

    def test_cash_payment_auto_submits_and_closes_order(self):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(self.order.cashier_id, self.user.id)
        self.assertEqual(response.data['payment']['method'], Payment.Method.CASH)
        self.assertEqual(response.data['receipt']['status'], 'failed')

    def test_closed_order_cannot_be_paid_twice(self):
        first_response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total},
            format='json',
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)

        second_response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', second_response.data)

    def test_card_pay_endpoint_requires_online_local_agent(self):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Local agent is offline', response.data['detail'])
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.status, Payment.Status.FAILED)

    @patch('apps.integrations.services.agent_marta.LocalAgentCommandService.local_http_request')
    def test_card_payment_uses_local_agent_and_closes_order_on_success(self, local_http_request):
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

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': self.order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_ref, 'trx-1')
        self.assertEqual(payment.provider_payload['transport'], 'local-agent')
        self.assertEqual(local_http_request.call_count, 2)

    def test_initiate_card_payment_requires_marta_config_on_active_cash_desk(self):
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/card-payments/initiate/',
            {'amount': self.order.total, 'register_fiscal': True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('active cash desk', response.data['detail'])
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    def test_initiate_card_payment_creates_pending_payment_and_returns_marta_config(self):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={
                'endpoint_url': 'http://192.168.88.125:8090',
                'amount_multiplier': 100,
                'tax_number': '307678400',
                'timeout_seconds': 180,
                'hmac_secret': 'secret',
            },
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/card-payments/initiate/',
            {'amount': self.order.total, 'register_fiscal': True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.method, Payment.Method.CARD)
        self.assertEqual(response.data['marta']['endpointUrl'], 'http://192.168.88.125:8090')
        self.assertEqual(response.data['marta']['amount'], 3300000)
        self.assertEqual(response.data['marta']['taxNumber'], '307678400')
        self.assertNotIn('hmac_secret', response.data['marta'])

    def test_terminal_success_completes_payment_and_closes_order(self):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        initiate_response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/card-payments/initiate/',
            {'amount': self.order.total, 'register_fiscal': True},
            format='json',
        )

        response = self.client.post(
            f"/api/v1/pos/billing/payments/{initiate_response.data['payment']['id']}/terminal-result/",
            {
                'ok': True,
                'status': 'SUCCESS',
                'requestId': 'request-1',
                'params': {'trxId': 'trx-1', 'rrn': 'rrn-1'},
                'debug': {'transaction': {'response': {'httpStatus': 200}}},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_ref, 'trx-1')
        self.assertEqual(payment.provider_payload['params']['trxId'], 'trx-1')

    def test_terminal_failure_marks_payment_failed_and_keeps_order_open(self):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        initiate_response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/card-payments/initiate/',
            {'amount': self.order.total, 'register_fiscal': True},
            format='json',
        )

        response = self.client.post(
            f"/api/v1/pos/billing/payments/{initiate_response.data['payment']['id']}/terminal-result/",
            {
                'ok': False,
                'status': 'CANCELED',
                'requestId': 'request-2',
                'message': 'Прекращено',
                'debug': {'transaction': {'response': {'httpStatus': 200}}},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Прекращено')
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertNotEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(payment.provider_payload['debug']['transaction']['response']['httpStatus'], 200)

    def test_delivery_card_payment_initiate_does_not_route_to_kitchen(self):
        order = self.create_delivery_order()
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{order.id}/card-payments/initiate/',
            {'amount': self.order.total, 'register_fiscal': True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    def test_delivery_terminal_failure_keeps_order_open_without_kitchen_ticket(self):
        order = self.create_delivery_order()
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        initiate_response = self.client.post(
            f'/api/v1/pos/billing/orders/{order.id}/card-payments/initiate/',
            {'amount': order.total, 'register_fiscal': True},
            format='json',
        )

        response = self.client.post(
            f"/api/v1/pos/billing/payments/{initiate_response.data['payment']['id']}/terminal-result/",
            {
                'ok': False,
                'status': 'CANCELED',
                'requestId': 'request-delivery',
                'message': 'Canceled',
                'debug': {'transaction': {'response': {'httpStatus': 200}}},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())

    @patch('apps.integrations.services.agent_marta.LocalAgentCommandService.local_http_request')
    def test_delivery_card_payment_success_routes_to_kitchen_after_payment(self, local_http_request):
        order = self.create_delivery_order()
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
                    'requestId': 'request-delivery-success',
                    'params': {'trxId': 'trx-delivery', 'rrn': 'rrn-delivery'},
                },
            },
        ]

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': order.total},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order.refresh_from_db()
        payment = Payment.objects.get(order=order)
        self.assertEqual(order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(KitchenTicket.objects.filter(order=order, prep_station=self.prep_station).exists())

