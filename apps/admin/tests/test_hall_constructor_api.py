from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Permission, Role, User
from apps.floor.models import DiningTable, Hall, TableSession
from apps.organizations.models import Branch, Restaurant


class AdminHallConstructorApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Test restaurant')
        cls.branch = Branch.objects.create(
            restaurant=cls.restaurant,
            name='Main branch',
            is_default=True,
        )
        cls.permission = Permission.objects.get_or_create(
            code='halls.update_layout',
            defaults={'name': 'Hall layout update', 'description': 'Hall layout update permission'},
        )[0]
        cls.role = Role.objects.get_or_create(
            code='constructor-admin',
            defaults={
                'name': 'Constructor Admin',
                'description': 'Admin role for hall constructor tests',
                'is_system': False,
            },
        )[0]
        cls.role.permissions.set([cls.permission])

        cls.user = User.objects.create_user(
            username='constructor-admin',
            password='secret123',
            full_name='Constructor Admin',
            restaurant=cls.restaurant,
            branch=cls.branch,
            role=cls.role,
            ui_mode=User.UiMode.ADMIN,
            is_staff=True,
        )
        cls.hall = Hall.objects.create(
            restaurant=cls.restaurant,
            branch=cls.branch,
            name='Asosiy zal',
            grid_columns=8,
            sort_order=1,
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

    def test_put_updates_layout_creates_and_hard_deletes_tables(self):
        self.authenticate()
        session = TableSession.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
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
                'grid_columns': 10,
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
        self.assertEqual(self.table_one.position_x, 2)
        self.assertEqual(self.table_one.position_y, 1)
        self.assertEqual(self.table_one.height, 2)
        self.assertEqual(self.table_one.shape_variant, DiningTable.ShapeVariant.SEAT4_VERTICAL)

        self.assertFalse(DiningTable.objects.filter(pk=self.table_two.pk).exists())
        self.assertFalse(TableSession.objects.filter(pk=session.pk).exists())
        self.assertTrue(DiningTable.objects.filter(hall=self.hall, table_number=12).exists())

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
