from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.billing.models import CashShift, Payment
from apps.integrations.models import IntegrationConfig
from apps.sales.models import Order, OrderItem
from apps.restaurants.models import CashDesk, DistributionPoint, Restaurant
from apps.platform.models import RestaurantEntitlement


class PaymentCreateApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Test restaurant',
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
        cls.item = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Osh',
        )
        cls.distribution_point = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
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
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )
        self.order.recalculate_totals()

    def test_takeaway_order_keeps_service_fee_zero(self):
        self.order.refresh_from_db()

        self.assertEqual(self.order.subtotal, 30000)
        self.assertEqual(self.order.total, 30000)

    def test_rejects_mixed_payment_method(self):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.MIXED, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('method', response.data)

    def test_cash_payment_auto_submits_and_closes_order(self):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 30000},
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
            {'method': Payment.Method.CASH, 'amount': 30000},
            format='json',
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)

        second_response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 30000},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', second_response.data)

    @patch('apps.integrations.services.MartaSoftPOSPaymentService')
    def test_card_payment_uses_marta_and_closes_order_on_success(self, service_class):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        service_class.return_value.charge_payment.return_value = {
            'ok': True,
            'provider': 'marta-softpos',
            'reference': 'trx-1',
            'params': {'trxId': 'trx-1', 'rrn': 'rrn-1'},
        }

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_ref, 'trx-1')
        self.assertEqual(payment.provider_payload['params']['trxId'], 'trx-1')

    @patch('apps.integrations.services.MartaSoftPOSPaymentService')
    def test_card_payment_requires_marta_config_on_active_cash_desk(self, service_class):
        IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('active cash desk', response.data['detail'])
        service_class.assert_not_called()

    @patch('apps.integrations.services.MartaSoftPOSPaymentService')
    def test_card_payment_returns_detail_on_marta_not_ready(self, service_class):
        marta_config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            is_enabled=True,
            settings={'endpoint_url': 'http://192.168.88.125:8090', 'amount_multiplier': 100},
        )
        self.cash_desk.payment_integration = marta_config
        self.cash_desk.save(update_fields=['payment_integration', 'updated_at'])
        service_class.return_value.charge_payment.return_value = {
            'ok': False,
            'provider': 'marta-softpos',
            'status': 'NOT_READY',
            'detail': 'SoftPOS is not ready. Open standby screen and keep the app in foreground',
        }

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CARD, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('standby screen', response.data['detail'])
        self.order.refresh_from_db()
        payment = Payment.objects.get(order=self.order)
        self.assertNotEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(payment.status, Payment.Status.FAILED)

