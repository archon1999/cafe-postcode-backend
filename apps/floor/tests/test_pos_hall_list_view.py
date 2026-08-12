from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from rest_framework.test import APIClient

from apps.users.models import Permission, User
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order
from apps.restaurants.models import DistributionPoint, PrepStation, Restaurant
from apps.platform.models import RestaurantEntitlement


class PosHallListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.restaurant = Restaurant.objects.create(name='Test restaurant')
        entitlement = RestaurantEntitlement.objects.create(
            restaurant=self.restaurant,
            is_active=True,
            is_custom=True,
        )
        entitlement.permissions.set([Permission.objects.get(code='pos_halls.view')])
        self.user = User.objects.create_user(
            username='admin',
            full_name='Admin User',
            is_superuser=True,
            is_staff=True,
            restaurant=self.restaurant,
        )
        self.client.force_authenticate(self.user)
        self.zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name='1-qavat',
            sort_order=1,
        )
        self.hall = Hall.objects.create(
            zone_or_cabin=self.zone,
            name='Asosiy zal',
            grid_columns=8,
            sort_order=1,
        )
        self.distribution_point = DistributionPoint.objects.create(
            restaurant=self.restaurant,
            name='Hall orders',
            kind=DistributionPoint.Kind.HALL,
        )
        self.prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )

        self.reserved_table = DiningTable.objects.create(
            hall=self.hall,
            zone=self.zone,
            name='Asosiy zal 4',
            table_number=4,
            seat_count=4,
            shape=DiningTable.Shape.SQUARE,
            shape_variant=DiningTable.ShapeVariant.SEAT4_SQUARE,
            status=DiningTable.Status.RESERVED,
            position_x=3,
            position_y=0,
            width=1,
            height=1,
        )
        self._create_active_table(
            table_number=3,
            position_x=2,
            position_y=0,
            width=1,
            height=1,
            session_status=TableSession.Status.OPEN,
            order_status=Order.Status.SUBMITTED,
            ticket_status=KitchenTicket.Status.NEW,
        )
        self._create_active_table(
            table_number=7,
            position_x=6,
            position_y=0,
            width=1,
            height=1,
            session_status=TableSession.Status.PENDING_PAYMENT,
            order_status=Order.Status.READY,
            ticket_status=KitchenTicket.Status.DONE,
        )

    def _create_active_table(
        self,
        *,
        table_number: int,
        position_x: int,
        position_y: int,
        width: int,
        height: int,
        session_status: str,
        order_status: str,
        ticket_status: str,
    ):
        table = DiningTable.objects.create(
            hall=self.hall,
            zone=self.zone,
            name=f'Asosiy zal {table_number}',
            table_number=table_number,
            seat_count=4,
            shape=DiningTable.Shape.RECTANGLE,
            shape_variant=DiningTable.ShapeVariant.SEAT4_VERTICAL if height > width else DiningTable.ShapeVariant.SEAT4_SQUARE,
            status=DiningTable.Status.OCCUPIED,
            position_x=position_x,
            position_y=position_y,
            width=width,
            height=height,
        )
        session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=2,
            status=session_status,
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=session,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=1000 + table_number,
            channel=Order.Channel.HALL,
            status=order_status,
            guest_count=2,
        )
        KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=order,
            prep_station=self.prep_station,
            status=ticket_status,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        return table

    def test_pos_halls_returns_positioned_tables_and_service_states(self):
        response = self.client.get('/api/v1/pos/floor/halls/')

        self.assertEqual(response.status_code, 200)
        halls = response.json()['data']
        self.assertEqual(len(halls), 1)
        self.assertNotIn('layoutObjects', halls[0])
        self.assertEqual(halls[0]['zoneOrCabin']['name'], '1-qavat')

        tables_by_number = {table['tableNumber']: table for table in halls[0]['tables']}

        self.assertEqual(halls[0]['gridColumns'], 8)
        self.assertEqual(float(tables_by_number[4]['positionX']), 3.0)
        self.assertEqual(tables_by_number[4]['status'], DiningTable.Status.RESERVED)
        self.assertEqual(tables_by_number[4]['zoneName'], '1-qavat')
        self.assertIsNone(tables_by_number[4]['activeSession'])
        self.assertEqual(tables_by_number[4]['activeSessions'], [])
        self.assertEqual(tables_by_number[4]['activeSessionCount'], 0)
        self.assertEqual(tables_by_number[4]['occupiedGuestCount'], 0)
        self.assertEqual(tables_by_number[4]['availableSeatCount'], 4)
        self.assertEqual(tables_by_number[3]['activeSession']['serviceState'], 'new')
        self.assertEqual(tables_by_number[3]['activeSessionCount'], 1)
        self.assertEqual(tables_by_number[3]['occupiedGuestCount'], 2)
        self.assertEqual(tables_by_number[3]['availableSeatCount'], 2)
        self.assertEqual(tables_by_number[7]['activeSession']['serviceState'], 'pending_payment')

    def test_pos_halls_preserves_active_session_filtering_order_and_occupancy(self):
        table = DiningTable.objects.get(table_number=3)
        original_session = table.table_sessions.get(status=TableSession.Status.OPEN)
        original_order = original_session.orders.get(status=Order.Status.SUBMITTED)
        KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=original_order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.DONE,
            dispatch_number=2,
        )

        latest_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=3,
            status=TableSession.Status.OPEN,
        )
        ignored_order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=latest_session,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=2003,
            channel=Order.Channel.HALL,
            status=Order.Status.CANCELLED,
            guest_count=3,
        )
        KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=ignored_order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.COOKING,
        )

        closed_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=table,
            opened_by=self.user,
            guest_count=20,
            status=TableSession.Status.CLOSED,
        )
        closed_order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=closed_session,
            distribution_point=self.distribution_point,
            opened_by=self.user,
            order_number=3003,
            channel=Order.Channel.HALL,
            status=Order.Status.CLOSED,
            guest_count=20,
        )
        KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=closed_order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.COOKING,
        )

        response = self.client.get('/api/v1/pos/floor/halls/')

        self.assertEqual(response.status_code, 200)
        tables = response.json()['data'][0]['tables']
        payload = next(row for row in tables if row['tableNumber'] == 3)
        self.assertEqual(
            [row['id'] for row in payload['activeSessions']],
            [str(latest_session.id), str(original_session.id)],
        )
        self.assertEqual(
            [row['serviceState'] for row in payload['activeSessions']],
            ['done', 'new'],
        )
        self.assertEqual(payload['activeSession']['id'], str(latest_session.id))
        self.assertEqual(payload['activeSessionCount'], 2)
        self.assertEqual(payload['occupiedGuestCount'], 5)
        self.assertEqual(payload['availableSeatCount'], 0)

    def test_pos_halls_query_count_is_bounded_as_table_count_grows(self):
        for table_number in range(10, 22):
            self._create_active_table(
                table_number=table_number,
                position_x=table_number,
                position_y=1,
                width=1,
                height=1,
                session_status=TableSession.Status.OPEN,
                order_status=Order.Status.SUBMITTED,
                ticket_status=KitchenTicket.Status.NEW,
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/v1/pos/floor/halls/')

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(queries),
            12,
            msg='\n'.join(query['sql'] for query in queries.captured_queries),
        )
