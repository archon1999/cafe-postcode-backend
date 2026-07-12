from rest_framework import status

from apps.users.models import Permission, Role, User
from apps.floor.models import DiningTable
from apps.sales.models import Order, OrderItem
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
        table_menu_payload = table_menu_response.data.get('data', table_menu_response.data)
        self.assertEqual(table_menu_payload[0]['image_url'], 'https://cdn.example.com/categories/plov.png')
        self.assertEqual(table_menu_payload[0]['items'][0]['image_url'], 'https://cdn.example.com/osh.png')

        self.client.force_authenticate(self.takeaway_user)
        takeaway_menu_response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(takeaway_menu_response.status_code, status.HTTP_200_OK)
        takeaway_menu_payload = takeaway_menu_response.data.get('data', takeaway_menu_response.data)
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
        self.assertEqual(takeaway_success.status_code, status.HTTP_204_NO_CONTENT)
        takeaway_order.refresh_from_db()
        self.assertEqual(takeaway_order.status, Order.Status.CANCELLED)

        self.client.force_authenticate(self.hall_user)
        hall_manager_success = self.client.delete(f'/api/v1/pos/sales/orders/items/{hall_item.id}/')
        self.assertEqual(hall_manager_success.status_code, status.HTTP_204_NO_CONTENT)
        hall_order.refresh_from_db()
        self.assertEqual(hall_order.status, Order.Status.OPEN)

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


