from rest_framework import status
from rest_framework.test import APITestCase
from django.utils import timezone

from apps.accounts.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.orders.models import CashShift, Order, OrderItem, Payment
from apps.organizations.models import Branch, CashDesk, DistributionPoint, FeatureConfig, Restaurant


class PaymentCreateApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.branch = Branch.objects.create(
            restaurant=cls.restaurant,
            name='Main branch',
            service_fee_percent=10,
            is_default=True,
        )
        FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            hall_enabled=False,
            kitchen_enabled=False,
            cashier_enabled=True,
            owner_dashboard_enabled=True,
            order_entry_mode=FeatureConfig.OrderEntryMode.CASHIER_BUILDER,
            kitchen_mode=FeatureConfig.KitchenMode.DISPLAY,
            enabled_modules=['cashier'],
            enabled_roles=['cashier'],
        )
        cls.permission = Permission.objects.get_or_create(
            code='payments.manage',
            defaults={'name': 'Payments manage', 'description': 'Payments manage permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='payments-cashier',
            defaults={'name': 'Payments cashier', 'description': 'Payments cashier role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission])
        cls.user = User.objects.create_user(
            username='payments-cashier',
            password='secret123',
            full_name='Payments Cashier',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.role,
            ui_mode=User.UiMode.POS,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            name='Asosiy',
            mxik_code='10000000000000001',
            mxik_name='Asosiy',
            kind=CatalogCategory.Kind.DISH,
        )
        cls.item = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            category=cls.category,
            name='Osh',
            kind=CatalogItem.Kind.DISH,
        )
        cls.distribution_point = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            name='Takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )
        cls.cash_desk = CashDesk.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            name='Main cashier',
            location='Front desk',
            enabled_payment_methods=['cash', 'card', 'qr'],
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.cash_shift = CashShift.objects.create(
            branch=self.branch,
            cash_desk=self.cash_desk,
            opened_by=self.user,
            opened_at=timezone.now(),
            opening_cash_amount=0,
        )
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
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
            f'/api/v1/pos/payments/orders/{self.order.id}/pay/',
            {'method': Payment.Method.MIXED, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('method', response.data)

    def test_cash_payment_auto_submits_and_closes_order(self):
        response = self.client.post(
            f'/api/v1/pos/payments/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 30000},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CLOSED)
        self.assertEqual(self.order.cashier_id, self.user.id)
        self.assertEqual(response.data['payment']['method'], Payment.Method.CASH)
        self.assertEqual(response.data['receipt']['status'], 'sent')

    def test_closed_order_cannot_be_paid_twice(self):
        first_response = self.client.post(
            f'/api/v1/pos/payments/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 30000},
            format='json',
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)

        second_response = self.client.post(
            f'/api/v1/pos/payments/orders/{self.order.id}/pay/',
            {'method': Payment.Method.CASH, 'amount': 30000},
            format='json',
        )

        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', second_response.data)
