from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.orders.models import Order, OrderItem
from apps.organizations.models import Branch, DistributionPoint, FeatureConfig, Restaurant


class OrderStateApiTests(APITestCase):
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
        )
        cls.permission = Permission.objects.get_or_create(
            code='orders.manage',
            defaults={'name': 'Orders manage', 'description': 'Orders manage permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='orders-manager',
            defaults={'name': 'Orders manager', 'description': 'Orders manager role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission])
        cls.user = User.objects.create_user(
            username='orders-manager',
            password='secret123',
            full_name='Orders Manager',
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

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_order_create_uses_branch_counter_sequence(self):
        first_response = self.client.post(
            '/api/v1/pos/orders/',
            {
                'distribution_point': str(self.distribution_point.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            },
            format='json',
        )
        second_response = self.client.post(
            '/api/v1/pos/orders/',
            {
                'distribution_point': str(self.distribution_point.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            },
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.data['order_number'], 1)
        self.assertEqual(second_response.data['order_number'], 2)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.last_order_number, 2)

    def test_closed_order_item_update_is_rejected(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            cashier=self.user,
            order_number=10,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
        )
        order_item = OrderItem.objects.create(
            order=order,
            catalog_item=self.item,
            created_by=self.user,
            quantity=1,
            unit_price=30000,
        )

        response = self.client.patch(
            f'/api/v1/pos/orders/items/{order_item.id}/',
            {'quantity': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
