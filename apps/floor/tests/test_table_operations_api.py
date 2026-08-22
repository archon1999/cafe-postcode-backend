from rest_framework import status

from apps.floor.models import DiningTable, Hall, TableSession, TableSessionTable
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class TableOperationsApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.table.status = DiningTable.Status.AVAILABLE
        self.table.save(update_fields=['status', 'updated_at'])
        self.second_table = DiningTable.objects.create(
            hall=self.hall,
            zone=self.zone,
            name='Asosiy zal 2',
            table_number=2,
            seat_count=4,
        )
        self.other_hall = Hall.objects.create(
            zone_or_cabin=self.zone,
            name='Ikkinchi zal',
            sort_order=2,
        )
        self.other_table = DiningTable.objects.create(
            hall=self.other_hall,
            zone=self.zone,
            name='Ikkinchi zal 1',
            table_number=1,
            seat_count=6,
        )

    def _session(self, table, *, guests=2, note=''):
        session = self.create_table_session(table=table, guest_count=guests)
        session.note = note
        session.save(update_fields=['note', 'updated_at'])
        table.status = DiningTable.Status.OCCUPIED
        table.save(update_fields=['status', 'updated_at'])
        return session

    def _submitted_order(self, session, *, note, item_note):
        order_data = self.create_order_via_api(
            {
                'table_session': str(session.pk),
                'channel': Order.Channel.HALL,
                'guest_count': session.guest_count,
                'note': note,
            }
        )
        item = self.add_item_via_api(order_data['id'], note=item_note)
        self.submit_order_via_api(order_data['id'])
        return Order.objects.get(pk=order_data['id']), item

    def test_transfer_to_empty_table_moves_entire_session_across_halls(self):
        source = self._session(self.table, guests=3, note='Deraza yonida')
        order, item = self._submitted_order(source, note='Umumiy izoh', item_note='Piyozsiz')

        response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{source.pk}/transfer/',
            {
                'targetTableId': str(self.other_table.pk),
                'expectedTargetSessionIds': [],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['mode'], 'moved')
        source.refresh_from_db()
        order.refresh_from_db()
        self.table.refresh_from_db()
        self.other_table.refresh_from_db()
        self.assertEqual(source.table_id, self.other_table.pk)
        self.assertEqual(source.hall_id, self.other_hall.pk)
        self.assertEqual(order.table_session_id, source.pk)
        self.assertTrue(order.items.filter(pk=item['id'], note='Piyozsiz').exists())
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)
        self.assertEqual(self.other_table.status, DiningTable.Status.OCCUPIED)

    def test_transfer_to_occupied_table_merges_orders_items_tickets_and_notes(self):
        source = self._session(self.table, guests=2, note='Source session')
        target = self._session(self.second_table, guests=2, note='Target session')
        source_order, source_item = self._submitted_order(
            source,
            note='Source order',
            item_note='Achchiqsiz',
        )
        target_order, target_item = self._submitted_order(
            target,
            note='Target order',
            item_note='Sous alohida',
        )

        response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{source.pk}/transfer/',
            {
                'targetTableId': str(self.second_table.pk),
                'targetSessionId': str(target.pk),
                'expectedTargetSessionIds': [str(target.pk)],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['mode'], 'merged')
        source.refresh_from_db()
        target.refresh_from_db()
        source_order.refresh_from_db()
        target_order.refresh_from_db()
        self.table.refresh_from_db()
        self.second_table.refresh_from_db()
        self.assertEqual(source.status, TableSession.Status.MERGED)
        self.assertEqual(source.merged_into_id, target.pk)
        self.assertEqual(target.guest_count, 4)
        self.assertIn('Source session', target.note)
        self.assertEqual(source_order.status, Order.Status.CANCELLED)
        self.assertEqual(target_order.items.count(), 2)
        self.assertTrue(target_order.items.filter(pk=source_item['id'], note='Achchiqsiz').exists())
        self.assertTrue(target_order.items.filter(pk=target_item['id'], note='Sous alohida').exists())
        self.assertEqual(KitchenTicket.objects.filter(order=target_order).count(), 2)
        self.assertEqual(
            KitchenTicket.objects.filter(order=target_order).values_list('dispatch_number', flat=True).distinct().count(),
            2,
        )
        self.assertEqual(target_order.subtotal, 60000)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)
        self.assertEqual(self.second_table.status, DiningTable.Status.OCCUPIED)

    def test_transfer_detects_target_changed_since_confirmation(self):
        source = self._session(self.table)
        target = self._session(self.second_table)

        response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{source.pk}/transfer/',
            {
                'targetTableId': str(self.second_table.pk),
                'expectedTargetSessionIds': [],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        self.assertEqual(response.data['code'], 'TARGET_TABLE_CHANGED')
        source.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.status, TableSession.Status.OPEN)
        self.assertEqual(target.status, TableSession.Status.OPEN)

    def test_group_occupied_and_empty_tables_into_one_logical_session_then_ungroup(self):
        canonical = self._session(self.table, guests=2)
        occupied = self._session(self.second_table, guests=2)
        self._submitted_order(canonical, note='A', item_note='A item')
        self._submitted_order(occupied, note='B', item_note='B item')

        group_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{canonical.pk}/group/',
            {'tableIds': [str(self.second_table.pk)]},
            format='json',
        )

        self.assertEqual(group_response.status_code, status.HTTP_200_OK, group_response.data)
        canonical.refresh_from_db()
        occupied.refresh_from_db()
        self.assertEqual(occupied.status, TableSession.Status.MERGED)
        self.assertEqual(canonical.guest_count, 4)
        self.assertTrue(
            TableSessionTable.objects.filter(
                session=canonical,
                table=self.second_table,
                released_at__isnull=True,
            ).exists()
        )
        halls_response = self.client.get('/api/v1/pos/floor/halls/')
        self.assertEqual(halls_response.status_code, status.HTTP_200_OK, halls_response.data)
        serialized_tables = {
            table['id']: table
            for hall in halls_response.json()['data']
            for table in hall['tables']
        }
        self.assertEqual(serialized_tables[str(self.table.pk)]['activeSession']['id'], str(canonical.pk))
        self.assertEqual(serialized_tables[str(self.second_table.pk)]['activeSession']['id'], str(canonical.pk))
        self.assertCountEqual(
            serialized_tables[str(self.second_table.pk)]['activeSession']['tableIds'],
            [str(self.table.pk), str(self.second_table.pk)],
        )

        ungroup_response = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{canonical.pk}/ungroup/',
            {'tableIds': [str(self.second_table.pk)]},
            format='json',
        )

        self.assertEqual(ungroup_response.status_code, status.HTTP_200_OK, ungroup_response.data)
        self.second_table.refresh_from_db()
        self.assertEqual(self.second_table.status, DiningTable.Status.AVAILABLE)
        self.assertFalse(
            TableSessionTable.objects.filter(
                session=canonical,
                table=self.second_table,
                released_at__isnull=True,
            ).exists()
        )

    def test_group_rejects_cross_hall_and_payment_started_sessions(self):
        canonical = self._session(self.table, guests=2)
        order_data = self.create_order_via_api(
            {'table_session': str(canonical.pk), 'channel': Order.Channel.HALL}
        )
        order = Order.objects.get(pk=order_data['id'])
        order.total_override = 1000
        order.save(update_fields=['total_override', 'updated_at'])

        payment_started = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{canonical.pk}/group/',
            {'tableIds': [str(self.second_table.pk)]},
            format='json',
        )
        cross_hall = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{canonical.pk}/group/',
            {'tableIds': [str(self.other_table.pk)]},
            format='json',
        )

        self.assertEqual(payment_started.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(payment_started.data['code'], 'TABLE_ORDER_PAYMENT_STARTED')
        self.assertEqual(cross_hall.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(cross_hall.data['code'], {'TABLE_GROUP_HALL_MISMATCH', 'TABLE_ORDER_PAYMENT_STARTED'})

    def test_hall_deletion_cascades_historical_group_links(self):
        canonical = self._session(self.table)
        link = TableSessionTable.objects.create(
            session=canonical,
            table=self.second_table,
            joined_by=self.user,
        )

        self.hall.delete()

        self.assertFalse(TableSessionTable.objects.filter(pk=link.pk).exists())
