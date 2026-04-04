from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order, OrderItem
from apps.organizations.models import DistributionPoint, FeatureConfig, PrepStation, Restaurant, RestaurantEntitlement


class KitchenStatusApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.branch = cls.restaurant
        cls.feature_config = FeatureConfig.objects.create(
            restaurant=cls.restaurant,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
            owner_dashboard_enabled=True,
            order_entry_mode=FeatureConfig.OrderEntryMode.HALL,
            kitchen_mode=FeatureConfig.KitchenMode.PRINTER,
            enabled_modules=['hall', 'kitchen', 'cashier'],
            enabled_roles=['chef'],
        )
        cls.permission = Permission.objects.get_or_create(
            code='pos_kitchen_orders.update',
            defaults={'name': 'POS kitchen orders update', 'description': 'POS kitchen orders update permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='kitchen-chef',
            defaults={'name': 'Kitchen chef', 'description': 'Kitchen chef role', 'is_system': False},
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
            username='kitchen-chef',
            password='secret123',
            full_name='Kitchen Chef',
            restaurant=cls.restaurant,
            role=cls.role,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Asosiy',
            mxik_code='10000000000000001',
            mxik_name='Asosiy',
        )
        cls.catalog_item = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Manti',
        )
        cls.prep_station = PrepStation.objects.create(
            restaurant=cls.restaurant,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        cls.distribution_point = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Hall orders',
            kind=DistributionPoint.Kind.HALL,
        )

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=1002,
            channel=Order.Channel.HALL,
            status=Order.Status.SUBMITTED,
            guest_count=2,
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=28000,
            status=OrderItem.Status.NEW,
        )
        self.order.recalculate_totals()
        self.ticket = KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=self.order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.NEW,
            routed_via=KitchenTicket.RouteMode.PRINTER,
        )

    def test_printer_mode_rejects_item_status_updates(self):
        response = self.client.post(
            f'/api/v1/pos/kitchen/items/{self.item.id}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_printer_mode_rejects_ticket_status_updates(self):
        response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{self.ticket.id}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

