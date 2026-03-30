from django.test import TestCase

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.floor.models import DiningTable, Hall, TableSession
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order
from apps.organizations.models import Branch, DistributionPoint, FeatureConfig, PrepStation, Restaurant


class PosHallListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.restaurant = Restaurant.objects.create(name='Test restaurant')
        self.branch = Branch.objects.create(
            restaurant=self.restaurant,
            name='Main branch',
            is_default=True,
        )
        self.user = User.objects.create(
            username='admin',
            full_name='Admin User',
            is_superuser=True,
            is_staff=True,
            restaurant=self.restaurant,
            branch=self.branch,
        )
        FeatureConfig.objects.create(
            restaurant=self.restaurant,
            hall_enabled=True,
            kitchen_enabled=True,
            cashier_enabled=True,
            owner_dashboard_enabled=True,
            order_entry_mode=FeatureConfig.OrderEntryMode.HALL,
            kitchen_mode=FeatureConfig.KitchenMode.DISPLAY,
            enabled_modules=['hall', 'kitchen', 'cashier'],
            enabled_roles=['waiter', 'cashier', 'chef'],
        )
        self.client.force_authenticate(self.user)
        self.hall = Hall.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            level=1,
            name='Asosiy zal',
            grid_columns=8,
            sort_order=1,
        )
        self.distribution_point = DistributionPoint.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            name='Hall orders',
            kind=DistributionPoint.Kind.HALL,
        )
        self.prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )

        self.reserved_table = DiningTable.objects.create(
            hall=self.hall,
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
        self._create_active_table(
            table_number=17,
            position_x=0,
            position_y=2,
            width=1,
            height=2,
            session_status=TableSession.Status.OPEN,
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
            branch=self.branch,
            hall=self.hall,
            table=table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=2,
            status=session_status,
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
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
            branch=self.branch,
            order=order,
            prep_station=self.prep_station,
            status=ticket_status,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        return table

    def test_pos_halls_returns_positioned_tables_and_service_states(self):
        response = self.client.get('/api/v1/pos/halls/')

        self.assertEqual(response.status_code, 200)
        halls = response.json()['data']
        self.assertEqual(len(halls), 1)
        self.assertEqual(halls[0]['level'], 1)
        self.assertNotIn('zones', halls[0])
        self.assertNotIn('layoutObjects', halls[0])

        tables_by_number = {table['tableNumber']: table for table in halls[0]['tables']}

        self.assertEqual(halls[0]['gridColumns'], 8)
        self.assertEqual(float(tables_by_number[4]['positionX']), 3.0)
        self.assertEqual(float(tables_by_number[17]['height']), 2.0)
        self.assertEqual(tables_by_number[17]['shapeVariant'], DiningTable.ShapeVariant.SEAT4_VERTICAL)
        self.assertEqual(tables_by_number[4]['status'], DiningTable.Status.RESERVED)
        self.assertEqual(tables_by_number[3]['activeSession']['serviceState'], 'new')
        self.assertEqual(tables_by_number[7]['activeSession']['serviceState'], 'pending_payment')
        self.assertEqual(tables_by_number[17]['activeSession']['serviceState'], 'done')
