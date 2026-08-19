from uuid import uuid4

from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.floor.models import DiningTable, Hall, TableSession
from apps.floor.models import ZoneOrCabin
from apps.restaurants.models import Restaurant
from apps.platform.models import RestaurantEntitlement


class AdminHallConstructorApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.zone = ZoneOrCabin.objects.create(restaurant=cls.restaurant, name='Main zone', sort_order=1, is_active=True)
        cls.permission = Permission.objects.get_or_create(
            code='halls.view',
            defaults={'name': 'Hall view', 'description': 'Hall view permission'},
        )[0]
        cls.update_permission = Permission.objects.get_or_create(
            code='halls.update',
            defaults={'name': 'Hall update', 'description': 'Hall update permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='constructor-admin',
            defaults={
                'name': 'Constructor Admin',
                'description': 'Admin role for hall constructor tests',
                'is_system': False,
            },
        )[0]
        cls.role.permissions.set([cls.permission, cls.update_permission])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            is_custom=True,
        )
        cls.entitlement.permissions.set([cls.permission, cls.update_permission])
        cls.entitlement.allowed_roles.set([cls.role])

        cls.user = User.objects.create_user(
            username='constructor-admin',
            password='secret123',
            full_name='Constructor Admin',
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.hall = Hall.objects.create(
            zone_or_cabin=cls.zone,
            name='Asosiy zal',
            grid_columns=8,
            sort_order=1,
            is_active=True,
        )
        cls.table_one = DiningTable.objects.create(
            hall=cls.hall,
            name='1-stol',
            table_number=1,
            seat_count=4,
            shape=DiningTable.Shape.SQUARE,
            shape_variant=DiningTable.ShapeVariant.SEAT4_SQUARE,
            status=DiningTable.Status.AVAILABLE,
            position_x=0,
            position_y=0,
            width=1,
            height=1,
        )
        cls.table_two = DiningTable.objects.create(
            hall=cls.hall,
            name='2-stol',
            table_number=2,
            seat_count=2,
            shape=DiningTable.Shape.RECTANGLE,
            shape_variant=DiningTable.ShapeVariant.SEAT2_HORIZONTAL,
            status=DiningTable.Status.AVAILABLE,
            position_x=1,
            position_y=0,
            width=1,
            height=1,
        )

    def authenticate(self):
        self.client.force_authenticate(self.user)

    def test_get_returns_constructor_snapshot(self):
        self.authenticate()

        response = self.client.get(f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data['hall_id']), str(self.hall.id))
        self.assertEqual(response.data['hall_name'], 'Asosiy zal')
        self.assertEqual(response.data['grid_columns'], 8)
        self.assertEqual(len(response.data['tables']), 2)

        tables_by_number = {row['table_number']: row for row in response.data['tables']}
        self.assertEqual(tables_by_number[1]['shape_variant'], DiningTable.ShapeVariant.SEAT4_SQUARE)
        self.assertEqual(tables_by_number[2]['position_x'], 1)

    def test_put_updates_layout_creates_and_deletes_inactive_tables(self):
        self.authenticate()
        session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=self.table_two,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=2,
            status=TableSession.Status.CLOSED,
        )

        response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            {
                'grid_columns': 10,
                'service_fee_enabled': True,
                'service_fee_percent': 4,
                'tables': [
                    {
                        'id': str(self.table_one.id),
                        'name': '1-stol yangilandi',
                        'table_number': 1,
                        'seat_count': 4,
                        'shape_variant': 'seat4_vertical',
                        'position_x': 2,
                        'position_y': 1,
                        'width': 1,
                        'height': 2,
                        'service_fee_enabled': True,
                        'service_fee_percent': 2,
                        'is_active': True,
                    },
                    {
                        'name': '12-stol',
                        'table_number': 12,
                        'seat_count': 6,
                        'shape_variant': 'seat6_horizontal',
                        'position_x': 5,
                        'position_y': 0,
                        'width': 2,
                        'height': 1,
                        'service_fee_enabled': True,
                        'service_fee_percent': 5,
                        'is_active': True,
                    },
                ],
                'deleted_table_ids': [str(self.table_two.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.hall.refresh_from_db()
        self.table_one.refresh_from_db()
        self.assertEqual(self.hall.grid_columns, 10)
        self.assertTrue(self.hall.service_fee_enabled)
        self.assertEqual(self.hall.service_fee_percent, 4)
        self.assertEqual(self.table_one.position_x, 2)
        self.assertEqual(self.table_one.position_y, 1)
        self.assertEqual(self.table_one.height, 2)
        self.assertEqual(self.table_one.shape_variant, DiningTable.ShapeVariant.SEAT4_VERTICAL)
        self.assertTrue(self.table_one.service_fee_enabled)
        self.assertEqual(self.table_one.service_fee_percent, 2)

        self.assertFalse(DiningTable.objects.filter(pk=self.table_two.pk).exists())
        self.assertFalse(TableSession.objects.filter(pk=session.pk).exists())
        created_table = DiningTable.objects.get(hall=self.hall, table_number=12)
        self.assertTrue(created_table.service_fee_enabled)
        self.assertEqual(created_table.service_fee_percent, 5)

    def test_put_rejects_deleting_table_with_active_session(self):
        self.authenticate()
        session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=self.table_two,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=2,
            status=TableSession.Status.OPEN,
        )

        response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            {
                'grid_columns': self.hall.grid_columns,
                'service_fee_enabled': self.hall.service_fee_enabled,
                'service_fee_percent': self.hall.service_fee_percent,
                'tables': [
                    {
                        'id': str(self.table_one.id),
                        'name': self.table_one.name,
                        'table_number': self.table_one.table_number,
                        'seat_count': self.table_one.seat_count,
                        'shape_variant': self.table_one.shape_variant,
                        'position_x': self.table_one.position_x,
                        'position_y': self.table_one.position_y,
                        'width': self.table_one.width,
                        'height': self.table_one.height,
                        'service_fee_enabled': self.table_one.service_fee_enabled,
                        'service_fee_percent': self.table_one.service_fee_percent,
                        'is_active': self.table_one.is_active,
                    }
                ],
                'deleted_table_ids': [str(self.table_two.id)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('deleted_table_ids', response.data)
        self.assertTrue(DiningTable.objects.filter(pk=self.table_two.pk).exists())
        self.assertTrue(TableSession.objects.filter(pk=session.pk).exists())

    def test_put_rejects_foreign_and_unknown_table_ids_without_an_oracle(self):
        self.authenticate()
        other_restaurant = Restaurant.objects.create(name='Other restaurant')
        other_zone = ZoneOrCabin.objects.create(
            restaurant=other_restaurant,
            name='Other zone',
            sort_order=1,
            is_active=True,
        )
        other_hall = Hall.objects.create(
            zone_or_cabin=other_zone,
            name='Other hall',
            grid_columns=8,
            sort_order=1,
            is_active=True,
        )
        foreign_table = DiningTable.objects.create(
            hall=other_hall,
            name='Foreign table',
            table_number=99,
            seat_count=4,
            shape=DiningTable.Shape.SQUARE,
            shape_variant=DiningTable.ShapeVariant.SEAT4_SQUARE,
            status=DiningTable.Status.AVAILABLE,
            position_x=0,
            position_y=0,
            width=1,
            height=1,
        )

        def payload(injected_id):
            return {
                'grid_columns': self.hall.grid_columns,
                'service_fee_enabled': self.hall.service_fee_enabled,
                'service_fee_percent': self.hall.service_fee_percent,
                'tables': [
                    {
                        'id': str(table.id),
                        'name': table.name,
                        'table_number': table.table_number,
                        'seat_count': table.seat_count,
                        'shape_variant': table.shape_variant,
                        'position_x': table.position_x,
                        'position_y': table.position_y,
                        'width': table.width,
                        'height': table.height,
                        'service_fee_enabled': table.service_fee_enabled,
                        'service_fee_percent': table.service_fee_percent,
                        'is_active': table.is_active,
                    }
                    for table in (self.table_one, self.table_two)
                ]
                + [
                    {
                        'id': str(injected_id),
                        'name': 'Injected table',
                        'table_number': 77,
                        'seat_count': 4,
                        'shape_variant': DiningTable.ShapeVariant.SEAT4_SQUARE,
                        'position_x': 3,
                        'position_y': 0,
                        'width': 1,
                        'height': 1,
                        'service_fee_enabled': False,
                        'service_fee_percent': 0,
                        'is_active': True,
                    }
                ],
                'deleted_table_ids': [],
            }

        foreign_response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            payload(foreign_table.id),
            format='json',
        )
        unknown_response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            payload(uuid4()),
            format='json',
        )

        self.assertEqual(foreign_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign_response.data, unknown_response.data)
        self.assertEqual(self.hall.tables.count(), 2)
        self.assertTrue(DiningTable.objects.filter(pk=foreign_table.pk).exists())

    def test_put_rejects_fractional_hall_and_table_service_fee_percent(self):
        self.authenticate()

        response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            {
                'grid_columns': 8,
                'service_fee_enabled': True,
                'service_fee_percent': 3.5,
                'tables': [
                    {
                        'id': str(self.table_one.id),
                        'name': self.table_one.name,
                        'table_number': self.table_one.table_number,
                        'seat_count': self.table_one.seat_count,
                        'shape_variant': self.table_one.shape_variant,
                        'position_x': 0,
                        'position_y': 0,
                        'width': 1,
                        'height': 1,
                        'service_fee_enabled': True,
                        'service_fee_percent': 2.5,
                        'is_active': True,
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('service_fee_percent', response.data)

    def test_put_rejects_overlapping_tables(self):
        self.authenticate()

        response = self.client.put(
            f'/api/v1/admin/floor/halls/{self.hall.id}/constructor/',
            {
                'grid_columns': 8,
                'tables': [
                    {
                        'id': str(self.table_one.id),
                        'name': '1-stol',
                        'table_number': 1,
                        'seat_count': 4,
                        'shape_variant': 'seat4_square',
                        'position_x': 0,
                        'position_y': 0,
                        'width': 2,
                        'height': 2,
                    },
                    {
                        'id': str(self.table_two.id),
                        'name': '2-stol',
                        'table_number': 2,
                        'seat_count': 2,
                        'shape_variant': 'seat2_horizontal',
                        'position_x': 1,
                        'position_y': 1,
                        'width': 1,
                        'height': 1,
                    },
                ],
                'deleted_table_ids': [],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tables', response.data)
