from datetime import timedelta
from uuid import uuid4

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.kitchen.models import KitchenAnnouncement, KitchenTicket, KitchenTicketLine
from apps.sales.models import Order, OrderItem
from apps.restaurants.models import DistributionPoint, PrepStation, Restaurant
from apps.platform.models import RestaurantEntitlement


class KitchenStatusApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.branch = cls.restaurant
        cls.permission = Permission.objects.get_or_create(
            code='pos_kitchen_orders.update',
            defaults={'name': 'POS kitchen orders update', 'description': 'POS kitchen orders update permission'},
        )[0]
        cls.view_permission = Permission.objects.get_or_create(
            code='pos_kitchen_orders.view',
            defaults={'name': 'POS kitchen orders view', 'description': 'POS kitchen orders view permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='kitchen-chef',
            defaults={'name': 'Kitchen chef', 'description': 'Kitchen chef role', 'is_system': False},
        )[0]
        cls.role.permissions.set([cls.permission, cls.view_permission])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set([cls.permission, cls.view_permission])
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
            display_name='17',
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
            routed_via=KitchenTicket.RouteMode.DISPLAY,
        )
        KitchenTicketLine.objects.create(ticket=self.ticket, order_item=self.item)

    def test_item_status_update_marks_item_done(self):
        response = self.client.post(
            f'/api/v1/pos/kitchen/items/{self.item.id}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, OrderItem.Status.DONE)

    def test_ticket_status_update_marks_order_ready(self):
        response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{self.ticket.id}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.ticket.status, KitchenTicket.Status.DONE)
        self.assertEqual(self.order.status, Order.Status.READY)
        announcement = KitchenAnnouncement.objects.get(order=self.order, kind=KitchenAnnouncement.Kind.AUTO)
        self.assertEqual(announcement.display_name, '17')
        self.assertEqual(announcement.locale, KitchenAnnouncement.Locale.UZ)

    def test_ready_order_can_be_announced_again_from_kitchen(self):
        ready_response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{self.ticket.id}/status/',
            {'status': 'done'},
            format='json',
        )
        self.assertEqual(ready_response.status_code, status.HTTP_200_OK)

        replay_response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{self.ticket.id}/announce/',
            {},
            format='json',
        )

        self.assertEqual(replay_response.status_code, status.HTTP_201_CREATED, replay_response.data)
        self.assertEqual(replay_response.data['display_name'], '17')
        self.assertEqual(replay_response.data['kind'], KitchenAnnouncement.Kind.REPLAY)
        self.assertEqual(KitchenAnnouncement.objects.filter(order=self.order).count(), 2)

    def test_status_retry_does_not_duplicate_automatic_announcement(self):
        for _attempt in range(2):
            response = self.client.post(
                f'/api/v1/pos/kitchen/tickets/{self.ticket.id}/status/',
                {'status': 'done'},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            KitchenAnnouncement.objects.filter(order=self.order, kind=KitchenAnnouncement.Kind.AUTO).count(),
            1,
        )

    def test_queue_includes_station_without_assigned_cooks(self):
        response = self.client.get('/api/v1/pos/kitchen/queue/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(str(response.data['data'][0]['id']), str(self.ticket.id))
        self.assertEqual(response.data['data'][0]['items'][0]['sale_unit'], 'piece')
        self.assertEqual(response.data['data'][0]['display_name'], '17')
        self.assertEqual(response.data['data'][0]['channel'], Order.Channel.HALL)

    def test_queue_excludes_stale_new_ticket_for_closed_order(self):
        self.order.status = Order.Status.CLOSED
        self.order.closed_at = timezone.now() - timedelta(days=2)
        self.order.save(update_fields=['status', 'closed_at', 'updated_at'])
        KitchenTicket.objects.filter(pk=self.ticket.pk).update(created_at=timezone.now() - timedelta(days=2))

        response = self.client.get('/api/v1/pos/kitchen/queue/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'], [])

    def test_status_updates_reject_foreign_resources_without_an_oracle(self):
        other_restaurant = Restaurant.objects.create(name='Foreign kitchen tenant')
        foreign_user = User.objects.create_user(
            username='foreign-kitchen-user',
            full_name='Foreign Kitchen User',
            restaurant=other_restaurant,
            role=self.role,
        )
        foreign_category = CatalogCategory.objects.create(
            restaurant=other_restaurant,
            name='Foreign category',
            mxik_code='10000000000000999',
            mxik_name='Foreign category',
        )
        foreign_catalog_item = CatalogItem.objects.create(
            restaurant=other_restaurant,
            category=foreign_category,
            name='Foreign dish',
        )
        foreign_station = PrepStation.objects.create(
            restaurant=other_restaurant,
            name='Foreign kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        foreign_distribution = DistributionPoint.objects.create(
            restaurant=other_restaurant,
            name='Foreign hall orders',
            kind=DistributionPoint.Kind.HALL,
        )
        foreign_order = Order.objects.create(
            restaurant=other_restaurant,
            distribution_point=foreign_distribution,
            opened_by=foreign_user,
            order_number=9002,
            channel=Order.Channel.HALL,
            status=Order.Status.SUBMITTED,
            guest_count=1,
        )
        foreign_item = OrderItem.objects.create(
            order=foreign_order,
            catalog_item=foreign_catalog_item,
            prep_station=foreign_station,
            created_by=foreign_user,
            quantity=1,
            unit_price=1000,
            status=OrderItem.Status.NEW,
        )
        foreign_ticket = KitchenTicket.objects.create(
            restaurant=other_restaurant,
            order=foreign_order,
            prep_station=foreign_station,
            status=KitchenTicket.Status.NEW,
            routed_via=KitchenTicket.RouteMode.DISPLAY,
        )
        KitchenTicketLine.objects.create(
            ticket=foreign_ticket,
            order_item=foreign_item,
        )

        foreign_item_response = self.client.post(
            f'/api/v1/pos/kitchen/items/{foreign_item.id}/status/',
            {'status': OrderItem.Status.DONE},
            format='json',
        )
        unknown_item_response = self.client.post(
            f'/api/v1/pos/kitchen/items/{uuid4()}/status/',
            {'status': OrderItem.Status.DONE},
            format='json',
        )
        foreign_ticket_response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{foreign_ticket.id}/status/',
            {'status': KitchenTicket.Status.DONE},
            format='json',
        )
        unknown_ticket_response = self.client.post(
            f'/api/v1/pos/kitchen/tickets/{uuid4()}/status/',
            {'status': KitchenTicket.Status.DONE},
            format='json',
        )

        self.assertEqual(
            foreign_item_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            unknown_item_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(foreign_item_response.data, unknown_item_response.data)
        self.assertEqual(
            foreign_ticket_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            unknown_ticket_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            foreign_ticket_response.data,
            unknown_ticket_response.data,
        )

        foreign_item.refresh_from_db()
        foreign_ticket.refresh_from_db()
        foreign_order.refresh_from_db()
        self.assertEqual(foreign_item.status, OrderItem.Status.NEW)
        self.assertEqual(foreign_ticket.status, KitchenTicket.Status.NEW)
        self.assertEqual(foreign_order.status, Order.Status.SUBMITTED)

