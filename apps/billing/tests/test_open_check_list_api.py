from datetime import UTC, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.sales.models import Order, OrderItem
from apps.restaurants.models import DistributionPoint, Restaurant
from apps.platform.models import RestaurantEntitlement
from common.utils.date import tashkent_day_bounds


class OpenCheckListApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Test restaurant',
            service_fee_enabled=True,
            service_fee_percent=10,
        )
        cls.branch = cls.restaurant
        cls.permission = Permission.objects.get_or_create(
            code='pos_open_checks.view',
            defaults={'name': 'POS open checks view', 'description': 'POS open checks view permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='open-checks-cashier',
            defaults={'name': 'Open checks cashier', 'description': 'Open checks cashier role', 'is_system': False},
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
            username='open-checks-cashier',
            password='secret123',
            full_name='Open Checks Cashier',
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
            name='Hall orders',
            kind=DistributionPoint.Kind.HALL,
        )

    def setUp(self):
        self.client.force_authenticate(self.user)

    @staticmethod
    def unwrap_response_items(response):
        if isinstance(response.data, dict) and 'data' in response.data:
            return response.data['data']
        return response.data

    def create_order(self, *, status: str, closed_at=None):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            cashier=self.user if status == Order.Status.CLOSED else None,
            order_number=1000 + Order.objects.count(),
            channel=Order.Channel.HALL,
            status=status,
            guest_count=2,
            closed_at=closed_at,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.item,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
            status=OrderItem.Status.NEW,
            note='Issiqroq',
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.item,
            created_by=self.user,
            quantity=1,
            unit_price=15000,
            status=OrderItem.Status.CANCELLED,
            note='Bekor qilindi',
        )
        order.recalculate_totals()
        return order

    def create_success_payment(self, *, order, register_fiscal=False):
        return Payment.objects.create(
            order=order,
            method=Payment.Method.CASH,
            amount=order.total,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=register_fiscal,
            paid_at=timezone.now(),
        )

    def test_open_status_returns_submitted_and_ready_orders(self):
        submitted_order = self.create_order(status=Order.Status.SUBMITTED)
        ready_order = self.create_order(status=Order.Status.READY)
        self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertEqual(returned_ids, {str(submitted_order.id), str(ready_order.id)})

    def test_open_status_respects_limit(self):
        self.create_order(status=Order.Status.SUBMITTED)
        self.create_order(status=Order.Status.SUBMITTED)
        self.create_order(status=Order.Status.READY)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open&limit=2')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.unwrap_response_items(response)), 2)

    def test_open_status_allows_full_list(self):
        self.create_order(status=Order.Status.SUBMITTED)
        self.create_order(status=Order.Status.SUBMITTED)
        self.create_order(status=Order.Status.READY)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open&limit=all')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.unwrap_response_items(response)), 3)

    def test_invalid_limit_returns_validation_error(self):
        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open&limit=bad')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('limit', response.data)

    def test_closed_status_returns_only_today_closed_orders(self):
        today_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        yesterday_order = self.create_order(
            status=Order.Status.CLOSED,
            closed_at=timezone.now() - timedelta(days=1),
        )
        self.create_success_payment(order=today_order)
        self.create_success_payment(order=yesterday_order)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertEqual(returned_ids, {str(today_order.id)})
        self.assertNotIn(str(yesterday_order.id), returned_ids)

    def test_closed_status_uses_tashkent_day_boundaries(self):
        start, _end = tashkent_day_bounds()
        included_order = self.create_order(
            status=Order.Status.CLOSED,
            closed_at=(start + timedelta(minutes=30)).astimezone(UTC),
        )
        excluded_order = self.create_order(
            status=Order.Status.CLOSED,
            closed_at=(start - timedelta(minutes=30)).astimezone(UTC),
        )
        self.create_success_payment(order=included_order)
        self.create_success_payment(order=excluded_order)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertIn(str(included_order.id), returned_ids)
        self.assertNotIn(str(excluded_order.id), returned_ids)

    def test_order_detail_includes_cancelled_items_for_cashier_detail(self):
        order = self.create_order(status=Order.Status.SUBMITTED)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        statuses = {item['status'] for item in payload['items']}
        self.assertIn(OrderItem.Status.CANCELLED, statuses)

    def test_open_status_omits_billing_details(self):
        order = self.create_order(status=Order.Status.SUBMITTED)
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.CASH,
            amount=order.total,
            status=Payment.Status.SUCCEEDED,
            provider_payload={'large': 'payload'},
        )
        Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.SENT,
            payload={'receiptNumber': 'R-1'},
        )

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        self.assertEqual(payload['payments'], [])
        self.assertEqual(payload['receipts'], [])

    def test_closed_status_returns_minimal_billing_details(self):
        order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        payment = self.create_success_payment(order=order)
        payment.provider_payload = {'large': 'payload'}
        payment.save(update_fields=['provider_payload', 'updated_at'])
        PaymentRefund.objects.create(
            payment=payment,
            amount=order.total,
            status=PaymentRefund.Status.SUCCEEDED,
        )
        Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.SENT,
            payload={'receiptNumber': 'R-1'},
        )

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        self.assertEqual(payload['payments'][0]['id'], str(payment.id))
        self.assertEqual(payload['payments'][0]['refunds_total'], order.total)
        self.assertTrue(payload['payments'][0]['is_refunded'])
        self.assertNotIn('provider_payload', payload['payments'][0])
        self.assertEqual(payload['receipts'][0]['payload']['receiptNumber'], 'R-1')

    def test_closed_status_excludes_fiscal_sent_orders(self):
        plain_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        fiscal_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        plain_payment = self.create_success_payment(order=plain_order)
        fiscal_payment = self.create_success_payment(order=fiscal_order, register_fiscal=True)
        Receipt.objects.create(
            order=fiscal_order,
            payment=fiscal_payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={'receiptNumber': 'F-1'},
        )

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertIn(str(plain_order.id), returned_ids)
        self.assertNotIn(str(fiscal_order.id), returned_ids)

    def test_closed_status_supports_search_and_pagination(self):
        matched_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        matched_order.display_name = 'VIP 777'
        matched_order.save(update_fields=['display_name', 'updated_at'])
        other_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        self.create_success_payment(order=matched_order)
        self.create_success_payment(order=other_order)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=closed&search=VIP&page=1&page_size=20')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['page_size'], 20)
        self.assertEqual(response.data['count'], 1)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertEqual(returned_ids, {str(matched_order.id)})

    def test_fiscal_closed_status_returns_fiscal_sent_orders(self):
        plain_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        fiscal_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        self.create_success_payment(order=plain_order)
        fiscal_payment = self.create_success_payment(order=fiscal_order, register_fiscal=True)
        Receipt.objects.create(
            order=fiscal_order,
            payment=fiscal_payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            payload={'receiptNumber': 'F-1'},
        )

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=fiscal_closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertEqual(returned_ids, {str(fiscal_order.id)})

    def test_hall_order_applies_restaurant_service_fee_percent(self):
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save(update_fields=['vat_enabled', 'vat_percent'])
        order = self.create_order(status=Order.Status.SUBMITTED)

        response = self.client.get('/api/v1/pos/billing/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        self.assertEqual(payload['subtotal'], 30000)
        self.assertEqual(payload['service_fee'], 3000)
        self.assertEqual(payload['service_fee_percent'], 10)
        self.assertTrue(payload['vat_enabled'])
        self.assertEqual(payload['vat_percent'], 12)
        self.assertEqual(payload['vat_amount'], 3536)
        self.assertEqual(payload['total'], 33000)
