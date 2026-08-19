from uuid import uuid4

from rest_framework import status

from apps.users.models import Permission, Role, User
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.restaurants.models import Restaurant
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
        self.assertEqual(success_response.data['table_number'], self.table.table_number)
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

    def test_table_session_table_is_create_only_and_move_action_updates_hall(self):
        target_hall = Hall.objects.create(
            zone_or_cabin=self.zone,
            name='Secondary hall',
        )
        target_table = DiningTable.objects.create(
            hall=target_hall,
            zone=self.zone,
            name='Secondary hall 1',
            table_number=1,
            seat_count=4,
        )

        self.client.force_authenticate(self.table_manager_user)
        session_id = uuid4()
        create_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {
                'id': str(session_id),
                'table': str(self.table.id),
                'guest_count': 2,
            },
            format='json',
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )
        self.assertEqual(create_response.data['id'], str(session_id))
        session = TableSession.objects.get(pk=session_id)

        patch_response = self.client.patch(
            f'/api/v1/pos/floor/table-sessions/{session.id}/',
            {
                'id': str(uuid4()),
                'table': str(target_table.id),
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('id', patch_response.data)
        self.assertIn('table', patch_response.data)
        session.refresh_from_db()
        self.table.refresh_from_db()
        target_table.refresh_from_db()
        self.assertEqual(session.table_id, self.table.id)
        self.assertEqual(session.hall_id, self.hall.id)
        self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)
        self.assertEqual(target_table.status, DiningTable.Status.AVAILABLE)

        move_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{session.id}/move/',
            {'target_table_id': str(target_table.id)},
            format='json',
        )

        self.assertEqual(move_response.status_code, status.HTTP_200_OK, move_response.data)
        session.refresh_from_db()
        self.table.refresh_from_db()
        target_table.refresh_from_db()
        self.assertEqual(session.table_id, target_table.id)
        self.assertEqual(session.hall_id, target_hall.id)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)
        self.assertEqual(target_table.status, DiningTable.Status.OCCUPIED)

    def test_table_session_lifecycle_fields_cannot_be_generic_patched(self):
        self.client.force_authenticate(self.table_manager_user)
        create_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {'table': str(self.table.id), 'guest_count': 2},
            format='json',
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )
        session = TableSession.objects.get(pk=create_response.data['id'])

        for lifecycle_status in (
            TableSession.Status.CLOSED,
            TableSession.Status.MERGED,
        ):
            with self.subTest(lifecycle_status=lifecycle_status):
                patch_response = self.client.patch(
                    f'/api/v1/pos/floor/table-sessions/{session.id}/',
                    {
                        'status': lifecycle_status,
                        'closedAt': '2026-08-15T12:00:00Z',
                        'mergedInto': str(session.id),
                    },
                    format='json',
                )

                self.assertEqual(
                    patch_response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertIn('status', patch_response.data)
                session.refresh_from_db()
                self.table.refresh_from_db()
                self.assertEqual(session.status, TableSession.Status.OPEN)
                self.assertIsNone(session.closed_at)
                self.assertIsNone(session.merged_into_id)
                self.assertEqual(session.table_id, self.table.id)
                self.assertEqual(session.hall_id, self.hall.id)
                self.assertEqual(self.table.status, DiningTable.Status.OCCUPIED)

    def test_pos_and_admin_table_session_create_reject_foreign_restaurant_table(self):
        other_restaurant = Restaurant.objects.create(name='Foreign floor restaurant')
        other_zone = ZoneOrCabin.objects.create(
            restaurant=other_restaurant,
            name='Foreign zone',
        )
        other_hall = Hall.objects.create(
            zone_or_cabin=other_zone,
            name='Foreign hall',
        )
        other_table = DiningTable.objects.create(
            hall=other_hall,
            zone=other_zone,
            name='Foreign table',
            table_number=1,
        )
        payload = {'table': str(other_table.id), 'guest_count': 1}

        self.client.force_authenticate(self.table_manager_user)
        pos_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            payload,
            format='json',
        )

        superuser = User.objects.create_superuser(
            username='floor-scope-superuser',
            password='secret123',
            full_name='Floor Scope Superuser',
        )
        self.client.force_authenticate(superuser)
        self.client.credentials(
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )
        admin_response = self.client.post(
            '/api/v1/admin/floor/table-sessions/',
            payload,
            format='json',
        )

        self.assertEqual(pos_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('table', pos_response.data)
        self.assertEqual(admin_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('table', admin_response.data)
        self.assertFalse(TableSession.objects.filter(table=other_table).exists())
        other_table.refresh_from_db()
        self.assertEqual(other_table.status, DiningTable.Status.AVAILABLE)

        self.client.force_authenticate(self.table_manager_user)
        self.client.credentials()
        local_create_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {'table': str(self.table.id), 'guest_count': 1},
            format='json',
        )
        self.assertEqual(
            local_create_response.status_code,
            status.HTTP_201_CREATED,
            local_create_response.data,
        )
        local_session = TableSession.objects.get(pk=local_create_response.data['id'])
        self.table.refresh_from_db()
        other_table.refresh_from_db()
        source_status_before_move = self.table.status
        target_status_before_move = other_table.status

        move_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{local_session.id}/move/',
            {'target_table_id': str(other_table.id)},
            format='json',
        )

        self.assertEqual(move_response.status_code, status.HTTP_404_NOT_FOUND)
        local_session.refresh_from_db()
        self.table.refresh_from_db()
        other_table.refresh_from_db()
        self.assertEqual(local_session.table_id, self.table.id)
        self.assertEqual(local_session.hall_id, self.hall.id)
        self.assertEqual(self.table.status, source_status_before_move)
        self.assertEqual(other_table.status, target_status_before_move)

    def test_table_session_waiter_assignment_cannot_cross_restaurants(self):
        other_restaurant = Restaurant.objects.create(name='Foreign waiter restaurant')
        foreign_waiter = User.objects.create_user(
            username='foreign-table-session-waiter',
            full_name='Foreign Table Session Waiter',
            restaurant=other_restaurant,
            role=self.reservation_role,
        )
        self.client.force_authenticate(self.table_manager_user)
        create_response = self.client.post(
            '/api/v1/pos/floor/table-sessions/',
            {
                'table': str(self.table.id),
                'guest_count': 1,
            },
            format='json',
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )
        session = TableSession.objects.get(pk=create_response.data['id'])
        original_waiter_id = session.assigned_waiter_id

        foreign_response = self.client.patch(
            f'/api/v1/pos/floor/table-sessions/{session.id}/',
            {'assignedWaiter': str(foreign_waiter.id)},
            format='json',
        )
        unknown_response = self.client.patch(
            f'/api/v1/pos/floor/table-sessions/{session.id}/',
            {'assignedWaiter': str(uuid4())},
            format='json',
        )

        self.assertEqual(foreign_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign_response.data, unknown_response.data)
        session.refresh_from_db()
        self.assertEqual(session.assigned_waiter_id, original_waiter_id)

        local_response = self.client.patch(
            f'/api/v1/pos/floor/table-sessions/{session.id}/',
            {'assignedWaiter': str(self.reservation_user.id)},
            format='json',
        )
        self.assertEqual(
            local_response.status_code,
            status.HTTP_200_OK,
            local_response.data,
        )
        session.refresh_from_db()
        self.assertEqual(session.assigned_waiter_id, self.reservation_user.id)

    def test_move_and_merge_reject_foreign_sessions_without_an_oracle(self):
        other_restaurant = Restaurant.objects.create(name='Foreign session restaurant')
        other_zone = ZoneOrCabin.objects.create(
            restaurant=other_restaurant,
            name='Foreign session zone',
        )
        other_hall = Hall.objects.create(
            zone_or_cabin=other_zone,
            name='Foreign session hall',
        )
        other_table = DiningTable.objects.create(
            hall=other_hall,
            zone=other_zone,
            name='Foreign session table',
            table_number=1,
            seat_count=4,
        )
        foreign_user = User.objects.create_user(
            username='foreign-session-user',
            full_name='Foreign Session User',
            restaurant=other_restaurant,
            role=self.table_manager_role,
        )
        foreign_session = TableSession.objects.create(
            restaurant=other_restaurant,
            hall=other_hall,
            table=other_table,
            opened_by=foreign_user,
            assigned_waiter=foreign_user,
            guest_count=1,
        )
        local_session = TableSession.objects.create(
            restaurant=self.restaurant,
            hall=self.hall,
            table=self.table,
            opened_by=self.table_manager_user,
            assigned_waiter=self.table_manager_user,
            guest_count=1,
        )
        self.client.force_authenticate(self.table_manager_user)

        foreign_move_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{foreign_session.id}/move/',
            {'target_table_id': str(self.table.id)},
            format='json',
        )
        unknown_move_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{uuid4()}/move/',
            {'target_table_id': str(self.table.id)},
            format='json',
        )
        foreign_merge_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{local_session.id}/merge/',
            {'source_session_id': str(foreign_session.id)},
            format='json',
        )
        unknown_merge_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{local_session.id}/merge/',
            {'source_session_id': str(uuid4())},
            format='json',
        )

        self.assertEqual(
            foreign_move_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            unknown_move_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(foreign_move_response.data, unknown_move_response.data)
        self.assertEqual(
            foreign_merge_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            unknown_merge_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(foreign_merge_response.data, unknown_merge_response.data)

        local_session.refresh_from_db()
        foreign_session.refresh_from_db()
        self.assertEqual(local_session.status, TableSession.Status.OPEN)
        self.assertIsNone(local_session.merged_into_id)
        self.assertEqual(local_session.table_id, self.table.id)
        self.assertEqual(foreign_session.status, TableSession.Status.OPEN)
        self.assertIsNone(foreign_session.merged_into_id)
        self.assertEqual(foreign_session.table_id, other_table.id)


