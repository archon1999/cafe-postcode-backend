import uuid

from rest_framework import status

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.kitchen.models import KitchenTicketLine
from apps.restaurants.models import DistributionPoint, PrepStation, Restaurant
from apps.sales.models import Order, OrderItem, OrderItemMarking
from apps.sales.tests.support.pos_api import PosAPITestCase


class PosPermissionBranchingApiTests(PosAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hall_role = Role.objects.create(
            code='pos-hall-operator-role',
            name='POS Hall Operator Role',
            description='POS hall operator role',
            is_system=False,
        )
        cls.hall_role.permissions.set(Permission.objects.filter(code__in=['pos_tables.manage']))
        cls.takeaway_role = Role.objects.create(
            code='pos-takeaway-operator-role',
            name='POS Takeaway Operator Role',
            description='POS takeaway operator role',
            is_system=False,
        )
        cls.takeaway_role.permissions.set(Permission.objects.filter(code__in=['pos_takeaway_menu.view']))
        cls.table_menu_role = Role.objects.create(
            code='pos-table-menu-role',
            name='POS Table Menu Role',
            description='POS table menu role',
            is_system=False,
        )
        cls.table_menu_role.permissions.set(Permission.objects.filter(code__in=['pos_table_menu.view']))
        cls.payment_add_role = Role.objects.create(
            code='pos-payment-add-role',
            name='POS Payment Add Role',
            description='POS payment add role',
            is_system=False,
        )
        cls.payment_add_role.permissions.set(Permission.objects.filter(code__in=['pos_payment_order_items.create']))
        cls.payment_delete_role = Role.objects.create(
            code='pos-payment-delete-role',
            name='POS Payment Delete Role',
            description='POS payment delete role',
            is_system=False,
        )
        cls.payment_delete_role.permissions.set(Permission.objects.filter(code__in=['pos_payment_order_items.delete']))
        cls.entitlement.allowed_roles.add(cls.hall_role, cls.takeaway_role, cls.table_menu_role, cls.payment_add_role)
        cls.entitlement.allowed_roles.add(cls.payment_delete_role)

        cls.hall_user = User.objects.create_user(
            username='hall-operator-user',
            password='secret123',
            full_name='Hall Operator User',
            restaurant=cls.restaurant,
            role=cls.hall_role,
            is_staff=True,
        )
        cls.takeaway_user = User.objects.create_user(
            username='takeaway-operator-user',
            password='secret123',
            full_name='Takeaway Operator User',
            restaurant=cls.restaurant,
            role=cls.takeaway_role,
            is_staff=True,
        )
        cls.table_menu_user = User.objects.create_user(
            username='table-menu-user',
            password='secret123',
            full_name='Table Menu User',
            restaurant=cls.restaurant,
            role=cls.table_menu_role,
            is_staff=True,
        )
        cls.payment_add_user = User.objects.create_user(
            username='payment-add-user',
            password='secret123',
            full_name='Payment Add User',
            restaurant=cls.restaurant,
            role=cls.payment_add_role,
            is_staff=True,
        )
        cls.payment_delete_user = User.objects.create_user(
            username='payment-delete-user',
            password='secret123',
            full_name='Payment Delete User',
            restaurant=cls.restaurant,
            role=cls.payment_delete_role,
            is_staff=True,
        )

    def test_pos_menu_is_available_for_both_table_and_takeaway_menu_permissions(self):
        self.category.image_url = 'https://cdn.example.com/categories/plov.png'
        self.category.save(update_fields=['image_url', 'updated_at'])
        self.catalog_item.image_url = 'https://cdn.example.com/osh.png'
        self.catalog_item.save(update_fields=['image_url', 'updated_at'])

        self.client.force_authenticate(self.table_menu_user)
        table_menu_response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(table_menu_response.status_code, status.HTTP_200_OK)
        table_menu_payload = (
            table_menu_response.data.get('data', table_menu_response.data)
            if isinstance(table_menu_response.data, dict)
            else table_menu_response.data
        )
        self.assertEqual(table_menu_payload[0]['image_url'], 'https://cdn.example.com/categories/plov.png')
        self.assertEqual(table_menu_payload[0]['items'][0]['image_url'], 'https://cdn.example.com/osh.png')

        self.client.force_authenticate(self.takeaway_user)
        takeaway_menu_response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(takeaway_menu_response.status_code, status.HTTP_200_OK)
        takeaway_menu_payload = (
            takeaway_menu_response.data.get('data', takeaway_menu_response.data)
            if isinstance(takeaway_menu_response.data, dict)
            else takeaway_menu_response.data
        )
        self.assertEqual(takeaway_menu_payload[0]['image_url'], 'https://cdn.example.com/categories/plov.png')
        self.assertEqual(takeaway_menu_payload[0]['items'][0]['image_url'], 'https://cdn.example.com/osh.png')

    def test_order_create_requires_channel_specific_pos_permission(self):
        session = self.create_table_session()
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])

        hall_payload = {
            'table_session': str(session.id),
            'channel': Order.Channel.HALL,
            'guest_count': 2,
            'note': '',
        }
        takeaway_payload = {
            'channel': Order.Channel.TAKEAWAY,
            'guest_count': 1,
            'note': '',
        }
        counter_hall_payload = {
            'channel': Order.Channel.HALL,
            'guest_count': 1,
            'note': '',
        }

        self.client.force_authenticate(self.takeaway_user)
        hall_forbidden = self.client.post('/api/v1/pos/sales/orders/', hall_payload, format='json')
        self.assertEqual(hall_forbidden.status_code, status.HTTP_403_FORBIDDEN)
        counter_hall_success = self.client.post('/api/v1/pos/sales/orders/', counter_hall_payload, format='json')
        self.assertEqual(counter_hall_success.status_code, status.HTTP_201_CREATED, counter_hall_success.data)
        self.assertEqual(str(counter_hall_success.data['distribution_point']), str(self.hall_distribution.id))

        self.client.force_authenticate(self.hall_user)
        hall_success = self.client.post('/api/v1/pos/sales/orders/', hall_payload, format='json')
        self.assertEqual(hall_success.status_code, status.HTTP_201_CREATED, hall_success.data)
        self.assertEqual(str(hall_success.data['distribution_point']), str(self.hall_distribution.id))

        takeaway_forbidden = self.client.post('/api/v1/pos/sales/orders/', takeaway_payload, format='json')
        self.assertEqual(takeaway_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.takeaway_user)
        takeaway_success = self.client.post('/api/v1/pos/sales/orders/', takeaway_payload, format='json')
        self.assertEqual(takeaway_success.status_code, status.HTTP_201_CREATED, takeaway_success.data)
        self.assertEqual(str(takeaway_success.data['distribution_point']), str(self.takeaway_distribution.id))

    def test_order_create_rejects_distribution_point_channel_mismatch(self):
        self.client.force_authenticate(self.takeaway_user)
        response = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'distribution_point': str(self.hall_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': '',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('distribution_point', response.data)

    def test_generic_order_writes_cannot_control_lifecycle_or_structural_relations(self):
        invalid_create = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'channel': Order.Channel.TAKEAWAY,
                'status': Order.Status.CLOSED,
                'guest_count': 1,
            },
            format='json',
        )

        self.assertEqual(invalid_create.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('status', invalid_create.data)

        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
                'note': 'Original note',
            }
        )
        order = Order.objects.get(pk=order_data['id'])
        table_session = self.create_table_session()
        alternate_distribution = DistributionPoint.objects.create(
            restaurant=self.restaurant,
            name='Alternate takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )

        for field_name, value in (
            ('status', Order.Status.SUBMITTED),
            ('table_session', str(table_session.id)),
            ('distribution_point', str(alternate_distribution.id)),
        ):
            with self.subTest(field_name=field_name):
                response = self.client.patch(
                    f'/api/v1/pos/sales/orders/{order.id}/',
                    {field_name: value},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertIn(field_name, response.data)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertIsNone(order.table_session_id)
        self.assertEqual(order.distribution_point_id, self.takeaway_distribution.id)

    def test_closed_and_cancelled_orders_reject_generic_patch(self):
        for index, order_status in enumerate((Order.Status.CLOSED, Order.Status.CANCELLED), start=1):
            order = Order.objects.create(
                restaurant=self.restaurant,
                distribution_point=self.takeaway_distribution,
                opened_by=self.user,
                order_number=5300 + index,
                channel=Order.Channel.TAKEAWAY,
                status=order_status,
                guest_count=1,
                note='Immutable note',
            )

            with self.subTest(order_status=order_status):
                response = self.client.patch(
                    f'/api/v1/pos/sales/orders/{order.id}/',
                    {'note': 'Changed note'},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertIn('detail', response.data)
                order.refresh_from_db()
                self.assertEqual(order.note, 'Immutable note')

    def test_dispatched_item_snapshot_fields_cannot_be_generic_patched(self):
        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            }
        )
        item_data = self.add_item_via_api(
            order_data['id'],
            quantity=2,
            note='Original kitchen note',
        )
        self.submit_order_via_api(order_data['id'])
        order_item = OrderItem.objects.get(pk=item_data['id'])
        ticket_line = KitchenTicketLine.objects.select_related('ticket__print_document').get(
            order_item=order_item,
        )
        alternate_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Alternate item',
            prep_station=self.prep_station,
            price=45000,
        )

        for field_name, value in (
            ('catalog_item', str(alternate_item.id)),
            ('quantity', 3),
            ('status', OrderItem.Status.DONE),
            ('note', 'Mutated kitchen note'),
        ):
            with self.subTest(field_name=field_name):
                response = self.client.patch(
                    f'/api/v1/pos/sales/orders/items/{order_item.id}/',
                    {field_name: value},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertIn(field_name, response.data)

        order_item.refresh_from_db()
        self.assertEqual(order_item.catalog_item_id, self.catalog_item.id)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.status, OrderItem.Status.NEW)
        self.assertEqual(order_item.note, 'Original kitchen note')
        self.assertEqual(
            ticket_line.ticket.print_document.data_snapshot['items'][0]['quantity'],
            2,
        )
        self.assertEqual(
            ticket_line.ticket.print_document.data_snapshot['items'][0]['note'],
            'Original kitchen note',
        )

    def test_undispatched_item_quantity_and_note_remain_editable_but_status_does_not(self):
        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            }
        )
        item_data = self.add_item_via_api(order_data['id'])

        update_response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item_data['id']}/",
            {'quantity': 2, 'note': 'Updated note'},
            format='json',
        )
        status_response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item_data['id']}/",
            {'status': OrderItem.Status.DONE},
            format='json',
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.data)
        self.assertEqual(status_response.status_code, status.HTTP_400_BAD_REQUEST, status_response.data)
        self.assertIn('status', status_response.data)
        order_item = OrderItem.objects.get(pk=item_data['id'])
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.note, 'Updated note')
        self.assertEqual(order_item.status, OrderItem.Status.NEW)

    def test_generic_writes_reject_client_ids_guest_count_and_fee_snapshots(self):
        client_order_id = uuid.uuid4()
        create_with_id = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'id': str(client_order_id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            },
            format='json',
        )
        self.assertEqual(create_with_id.status_code, status.HTTP_400_BAD_REQUEST, create_with_id.data)
        self.assertIn('id', create_with_id.data)
        self.assertFalse(Order.objects.filter(pk=client_order_id).exists())

        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            }
        )
        order = Order.objects.get(pk=order_data['id'])
        original_snapshot = (
            order.guest_count,
            order.restaurant_service_fee_percent,
            order.hall_service_fee_percent,
            order.table_service_fee_percent,
        )
        replacement_order_id = uuid.uuid4()
        for field_name, value in (
            ('id', str(replacement_order_id)),
            ('guest_count', 99),
            ('restaurant_service_fee_percent', '99.00'),
            ('hall_service_fee_percent', '99.00'),
            ('table_service_fee_percent', '99.00'),
        ):
            with self.subTest(field_name=field_name):
                response = self.client.patch(
                    f'/api/v1/pos/sales/orders/{order.id}/',
                    {field_name: value},
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertIn(field_name, response.data)

        order.refresh_from_db()
        self.assertEqual(
            (
                order.guest_count,
                order.restaurant_service_fee_percent,
                order.hall_service_fee_percent,
                order.table_service_fee_percent,
            ),
            original_snapshot,
        )
        self.assertFalse(Order.objects.filter(pk=replacement_order_id).exists())

        client_item_id = uuid.uuid4()
        create_item_with_id = self.client.post(
            f'/api/v1/pos/sales/orders/{order.id}/items/',
            {
                'id': str(client_item_id),
                'catalog_item': str(self.catalog_item.id),
                'quantity': 1,
            },
            format='json',
        )
        self.assertEqual(create_item_with_id.status_code, status.HTTP_400_BAD_REQUEST, create_item_with_id.data)
        self.assertIn('id', create_item_with_id.data)
        self.assertFalse(OrderItem.objects.filter(pk=client_item_id).exists())

        item_data = self.add_item_via_api(order.id)
        replacement_item_id = uuid.uuid4()
        patch_item_id = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{item_data['id']}/",
            {'id': str(replacement_item_id)},
            format='json',
        )
        self.assertEqual(patch_item_id.status_code, status.HTTP_400_BAD_REQUEST, patch_item_id.data)
        self.assertIn('id', patch_item_id.data)
        self.assertTrue(OrderItem.objects.filter(pk=item_data['id']).exists())
        self.assertFalse(OrderItem.objects.filter(pk=replacement_item_id).exists())

    def test_marked_item_quantity_can_only_change_through_scan_flow(self):
        marked_catalog_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Marked drink',
            prep_station=self.prep_station,
            price=14000,
            requires_marking=True,
            marking_gtin='04780012960214',
        )
        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            }
        )
        item_response = self.client.post(
            f"/api/v1/pos/sales/orders/{order_data['id']}/items/",
            {'catalog_item': str(marked_catalog_item.id), 'quantity': 1},
            format='json',
        )
        self.assertEqual(item_response.status_code, status.HTTP_201_CREATED, item_response.data)
        order_item = OrderItem.objects.get(pk=item_response.data['id'])
        OrderItemMarking.objects.create(
            order_item=order_item,
            catalog_item=marked_catalog_item,
            raw_code='010478001296021421MARKED-ONE',
            gtin='04780012960214',
            serial='MARKED-ONE',
            scanned_by=self.user,
        )

        response = self.client.patch(
            f'/api/v1/pos/sales/orders/items/{order_item.id}/',
            {'quantity': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('quantity', response.data)
        order_item.refresh_from_db()
        self.assertEqual(order_item.quantity, 1)
        self.assertEqual(order_item.markings.count(), 1)

    def test_order_and_item_write_relations_are_scoped_to_order_restaurant(self):
        other_restaurant = Restaurant.objects.create(name='Foreign restaurant')
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
        other_session = TableSession.objects.create(
            restaurant=other_restaurant,
            hall=other_hall,
            table=other_table,
            opened_by=self.user,
            assigned_waiter=self.user,
            guest_count=1,
        )
        other_distribution = DistributionPoint.objects.create(
            restaurant=other_restaurant,
            name='Foreign takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )
        other_station = PrepStation.objects.create(
            restaurant=other_restaurant,
            name='Foreign kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        other_category = CatalogCategory.objects.create(
            restaurant=other_restaurant,
            name='Foreign category',
        )
        other_item = CatalogItem.objects.create(
            restaurant=other_restaurant,
            category=other_category,
            prep_station=other_station,
            name='Foreign item',
            price=10000,
        )

        self.client.force_authenticate(self.user)
        foreign_session_response = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'table_session': str(other_session.id),
                'channel': Order.Channel.HALL,
                'guest_count': 1,
            },
            format='json',
        )
        foreign_distribution_response = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'distribution_point': str(other_distribution.id),
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            },
            format='json',
        )

        self.assertEqual(foreign_session_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('table_session', foreign_session_response.data)
        self.assertEqual(foreign_distribution_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('distribution_point', foreign_distribution_response.data)

        order_data = self.create_order_via_api(
            {
                'channel': Order.Channel.TAKEAWAY,
                'guest_count': 1,
            }
        )
        order_id = order_data['id']
        foreign_item_response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {'catalog_item': str(other_item.id), 'quantity': 1},
            format='json',
        )
        foreign_bulk_response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/bulk/',
            {
                'items': [
                    {'catalog_item': str(other_item.id), 'quantity': 1},
                ]
            },
            format='json',
        )
        local_item = self.add_item_via_api(order_id)
        foreign_item_update_response = self.client.patch(
            f"/api/v1/pos/sales/orders/items/{local_item['id']}/",
            {'catalog_item': str(other_item.id)},
            format='json',
        )
        foreign_order_update_response = self.client.patch(
            f'/api/v1/pos/sales/orders/{order_id}/',
            {'distribution_point': str(other_distribution.id)},
            format='json',
        )

        self.assertEqual(foreign_item_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('catalog_item', foreign_item_response.data)
        self.assertEqual(foreign_bulk_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('items', foreign_bulk_response.data)
        self.assertEqual(foreign_item_update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('catalog_item', foreign_item_update_response.data)
        self.assertEqual(foreign_order_update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('distribution_point', foreign_order_update_response.data)

        saved_item = OrderItem.objects.get(pk=local_item['id'])
        self.assertEqual(saved_item.catalog_item_id, self.catalog_item.id)
        self.assertFalse(
            OrderItem.objects.filter(order_id=order_id, catalog_item=other_item).exists()
        )

    def test_order_item_and_submit_endpoints_use_order_context_permission(self):
        hall_session = self.create_table_session()
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        hall_order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=hall_session,
            distribution_point=self.hall_distribution,
            opened_by=self.hall_user,
            order_number=5001,
            channel=Order.Channel.HALL,
            status=Order.Status.OPEN,
            guest_count=2,
        )
        takeaway_order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.takeaway_user,
            order_number=5002,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )

        item_payload = {
            'catalog_item': str(self.catalog_item.id),
            'quantity': 1,
            'note': '',
        }

        self.client.force_authenticate(self.takeaway_user)
        hall_item_forbidden = self.client.post(f'/api/v1/pos/sales/orders/{hall_order.id}/items/', item_payload, format='json')
        self.assertEqual(hall_item_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.hall_user)
        hall_item_success = self.client.post(f'/api/v1/pos/sales/orders/{hall_order.id}/items/', item_payload, format='json')
        self.assertEqual(hall_item_success.status_code, status.HTTP_201_CREATED, hall_item_success.data)
        hall_submit_success = self.client.post(f'/api/v1/pos/sales/orders/{hall_order.id}/submit/', {}, format='json')
        self.assertEqual(hall_submit_success.status_code, status.HTTP_200_OK, hall_submit_success.data)

        self.client.force_authenticate(self.hall_user)
        takeaway_item_forbidden = self.client.post(
            f'/api/v1/pos/sales/orders/{takeaway_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(takeaway_item_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.takeaway_user)
        takeaway_item_success = self.client.post(
            f'/api/v1/pos/sales/orders/{takeaway_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(takeaway_item_success.status_code, status.HTTP_201_CREATED, takeaway_item_success.data)
        takeaway_submit_success = self.client.post(f'/api/v1/pos/sales/orders/{takeaway_order.id}/submit/', {}, format='json')
        self.assertEqual(takeaway_submit_success.status_code, status.HTTP_200_OK, takeaway_submit_success.data)

        self.client.force_authenticate(self.payment_add_user)
        payment_add_hall_forbidden = self.client.post(
            f'/api/v1/pos/sales/orders/{hall_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(payment_add_hall_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        payment_add_takeaway_success = self.client.post(
            f'/api/v1/pos/sales/orders/{takeaway_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(payment_add_takeaway_success.status_code, status.HTTP_201_CREATED, payment_add_takeaway_success.data)

        payment_add_submit_forbidden = self.client.post(f'/api/v1/pos/sales/orders/{takeaway_order.id}/submit/', {}, format='json')
        self.assertEqual(payment_add_submit_forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_payment_item_delete_permission_only_removes_takeaway_items(self):
        hall_session = self.create_table_session()
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        hall_order = Order.objects.create(
            restaurant=self.restaurant,
            table_session=hall_session,
            distribution_point=self.hall_distribution,
            opened_by=self.hall_user,
            order_number=5101,
            channel=Order.Channel.HALL,
            status=Order.Status.OPEN,
            guest_count=2,
        )
        takeaway_order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.takeaway_user,
            order_number=5102,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        hall_item = OrderItem.objects.create(
            order=hall_order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            unit_price=self.catalog_item.price,
        )
        takeaway_item = OrderItem.objects.create(
            order=takeaway_order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            unit_price=self.catalog_item.price,
        )

        self.client.force_authenticate(self.payment_delete_user)
        hall_forbidden = self.client.delete(f'/api/v1/pos/sales/orders/items/{hall_item.id}/')
        self.assertEqual(hall_forbidden.status_code, status.HTTP_403_FORBIDDEN)
        takeaway_success = self.client.delete(f'/api/v1/pos/sales/orders/items/{takeaway_item.id}/')
        self.assertEqual(takeaway_success.status_code, status.HTTP_200_OK)
        self.assertTrue(takeaway_success.data['orderRemoved'])
        self.assertFalse(Order.objects.filter(pk=takeaway_order.pk).exists())

        self.client.force_authenticate(self.hall_user)
        hall_manager_success = self.client.delete(f'/api/v1/pos/sales/orders/items/{hall_item.id}/')
        self.assertEqual(hall_manager_success.status_code, status.HTTP_200_OK)
        self.assertTrue(hall_manager_success.data['orderRemoved'])
        self.assertFalse(Order.objects.filter(pk=hall_order.pk).exists())

    def test_counter_draft_channel_change_updates_distribution_point(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.takeaway_user,
            order_number=5201,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )
        OrderItem.objects.create(
            order=order,
            catalog_item=self.catalog_item,
            prep_station=self.prep_station,
            created_by=self.takeaway_user,
            quantity=1,
            unit_price=30000,
        )
        order.recalculate_totals()
        self.assertEqual(order.total, 30000)

        self.client.force_authenticate(self.takeaway_user)
        response = self.client.patch(
            f'/api/v1/pos/sales/orders/{order.id}/',
            {'channel': Order.Channel.HALL},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order.refresh_from_db()
        self.assertEqual(order.channel, Order.Channel.HALL)
        self.assertEqual(order.distribution_point.kind, Order.Channel.HALL)
        self.assertEqual(order.service_fee_percent, 10)
        self.assertEqual(order.total, 33000)

        response = self.client.patch(
            f'/api/v1/pos/sales/orders/{order.id}/',
            {'channel': Order.Channel.TAKEAWAY},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order.refresh_from_db()
        self.assertEqual(order.channel, Order.Channel.TAKEAWAY)
        self.assertEqual(order.service_fee_percent, 0)
        self.assertEqual(order.total, 30000)


