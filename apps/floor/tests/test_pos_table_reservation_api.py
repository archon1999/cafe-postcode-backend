from rest_framework import status

from apps.users.models import Permission, Role, User
from apps.floor.models import DiningTable, TableSession
from apps.sales.tests.support.pos_api import PosAPITestCase


class PosTableReservationApiTests(PosAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.reservation_role = Role.objects.create(
            code='pos-reservation-role',
            name='POS Reservation Role',
            description='POS reservation role',
            is_system=False,
        )
        cls.reservation_role.permissions.set(Permission.objects.filter(code__in=['pos_table_reservations.manage']))
        cls.table_manager_role = Role.objects.create(
            code='pos-table-manager-role',
            name='POS Table Manager Role',
            description='POS table manager role',
            is_system=False,
        )
        cls.table_manager_role.permissions.set(Permission.objects.filter(code__in=['pos_tables.manage']))
        cls.entitlement.allowed_roles.add(cls.reservation_role, cls.table_manager_role)

        cls.reservation_user = User.objects.create_user(
            username='reservation-user',
            password='secret123',
            full_name='Reservation User',
            restaurant=cls.restaurant,
            role=cls.reservation_role,
            is_staff=True,
        )
        cls.table_manager_user = User.objects.create_user(
            username='table-manager-user',
            password='secret123',
            full_name='Table Manager User',
            restaurant=cls.restaurant,
            role=cls.table_manager_role,
            is_staff=True,
        )

    def test_reserve_endpoint_requires_reservation_permission(self):
        self.client.force_authenticate(self.table_manager_user)

        forbidden_response = self.client.post(f'/api/v1/pos/floor/tables/{self.table.id}/reserve/', {}, format='json')

        self.assertEqual(forbidden_response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.reservation_user)
        success_response = self.client.post(f'/api/v1/pos/floor/tables/{self.table.id}/reserve/', {}, format='json')

        self.assertEqual(success_response.status_code, status.HTTP_200_OK)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, DiningTable.Status.RESERVED)

    def test_reserved_table_can_only_be_opened_by_reservation_permission(self):
        self.table.status = DiningTable.Status.RESERVED
        self.table.save(update_fields=['status', 'updated_at'])

        payload = {
            'table': str(self.table.id),
            'guest_count': 2,
        }

        self.client.force_authenticate(self.table_manager_user)
        forbidden_response = self.client.post('/api/v1/pos/floor/table-sessions/', payload, format='json')

        self.assertEqual(forbidden_response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.reservation_user)
        success_response = self.client.post('/api/v1/pos/floor/table-sessions/', payload, format='json')

        self.assertEqual(success_response.status_code, status.HTTP_201_CREATED, success_response.data)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)

    def test_occupied_table_accepts_multiple_sessions_until_capacity_is_full(self):
        self.client.force_authenticate(self.table_manager_user)

        first_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {'table': str(self.table.id), 'guest_count': 2},
            format='json',
        )
        second_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {'table': str(self.table.id), 'guest_count': 2},
            format='json',
        )
        over_capacity_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {'table': str(self.table.id), 'guest_count': 1},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED, first_response.data)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED, second_response.data)
        self.assertEqual(over_capacity_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)
        self.assertEqual(
            TableSession.objects.filter(table=self.table, status=TableSession.Status.OPEN).count(),
            2,
        )


