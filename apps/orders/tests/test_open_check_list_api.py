from datetime import UTC, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.orders.models import Order, OrderItem
from apps.organizations.models import Branch, DistributionPoint, FeatureConfig, Restaurant
from common.utils.date import tashkent_day_bounds


class OpenCheckListApiTests(APITestCase):
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
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
            owner_dashboard_enabled=True,
            order_entry_mode=FeatureConfig.OrderEntryMode.HALL,
            kitchen_mode=FeatureConfig.KitchenMode.DISPLAY,
            enabled_modules=['hall', 'kitchen', 'cashier'],
            enabled_roles=['cashier'],
        )
        cls.permission = Permission.objects.get_or_create(
            code='payments.manage',
            defaults={'name': 'Payments manage', 'description': 'Payments manage permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='open-checks-cashier',
            defaults={'name': 'Open checks cashier', 'description': 'Open checks cashier role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission])
        cls.user = User.objects.create_user(
            username='open-checks-cashier',
            password='secret123',
            full_name='Open Checks Cashier',
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
            branch=self.branch,
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

    def test_open_status_returns_submitted_and_ready_orders(self):
        submitted_order = self.create_order(status=Order.Status.SUBMITTED)
        ready_order = self.create_order(status=Order.Status.READY)
        self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())

        response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertEqual(returned_ids, {str(submitted_order.id), str(ready_order.id)})

    def test_closed_status_returns_only_today_closed_orders(self):
        today_order = self.create_order(status=Order.Status.CLOSED, closed_at=timezone.now())
        yesterday_order = self.create_order(
            status=Order.Status.CLOSED,
            closed_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get('/api/v1/pos/payments/open-checks/?status=closed')

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

        response = self.client.get('/api/v1/pos/payments/open-checks/?status=closed')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item['id'] for item in self.unwrap_response_items(response)}
        self.assertIn(str(included_order.id), returned_ids)
        self.assertNotIn(str(excluded_order.id), returned_ids)

    def test_order_detail_includes_cancelled_items_for_cashier_detail(self):
        order = self.create_order(status=Order.Status.SUBMITTED)

        response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        statuses = {item['status'] for item in payload['items']}
        self.assertIn(OrderItem.Status.CANCELLED, statuses)

    def test_hall_order_applies_branch_service_fee_percent(self):
        order = self.create_order(status=Order.Status.SUBMITTED)

        response = self.client.get('/api/v1/pos/payments/open-checks/?status=open')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in self.unwrap_response_items(response) if item['id'] == str(order.id))
        self.assertEqual(payload['subtotal'], 30000)
        self.assertEqual(payload['service_fee'], 3000)
        self.assertEqual(payload['service_fee_percent'], 10)
        self.assertEqual(payload['total'], 33000)
