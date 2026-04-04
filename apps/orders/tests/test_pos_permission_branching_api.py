from rest_framework import status

from apps.accounts.models import Permission, Role, User
from apps.floor.models import DiningTable
from apps.orders.models import Order
from common.tests.pos_api import PosAPITestCase


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
        cls.entitlement.allowed_roles.add(cls.hall_role, cls.takeaway_role, cls.table_menu_role)

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

    def test_pos_menu_is_available_for_both_table_and_takeaway_menu_permissions(self):
        self.client.force_authenticate(self.table_menu_user)
        table_menu_response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(table_menu_response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.takeaway_user)
        takeaway_menu_response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(takeaway_menu_response.status_code, status.HTTP_200_OK)

    def test_order_create_requires_channel_specific_pos_permission(self):
        session = self.create_table_session()
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])

        hall_payload = {
            'table_session': str(session.id),
            'distribution_point': str(self.hall_distribution.id),
            'channel': Order.Channel.HALL,
            'guest_count': 2,
            'note': '',
        }
        takeaway_payload = {
            'distribution_point': str(self.takeaway_distribution.id),
            'channel': Order.Channel.TAKEAWAY,
            'guest_count': 1,
            'note': '',
        }

        self.client.force_authenticate(self.takeaway_user)
        hall_forbidden = self.client.post('/api/v1/pos/orders/', hall_payload, format='json')
        self.assertEqual(hall_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.hall_user)
        hall_success = self.client.post('/api/v1/pos/orders/', hall_payload, format='json')
        self.assertEqual(hall_success.status_code, status.HTTP_201_CREATED, hall_success.data)

        takeaway_forbidden = self.client.post('/api/v1/pos/orders/', takeaway_payload, format='json')
        self.assertEqual(takeaway_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.takeaway_user)
        takeaway_success = self.client.post('/api/v1/pos/orders/', takeaway_payload, format='json')
        self.assertEqual(takeaway_success.status_code, status.HTTP_201_CREATED, takeaway_success.data)

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
        hall_item_forbidden = self.client.post(f'/api/v1/pos/orders/{hall_order.id}/items/', item_payload, format='json')
        self.assertEqual(hall_item_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.hall_user)
        hall_item_success = self.client.post(f'/api/v1/pos/orders/{hall_order.id}/items/', item_payload, format='json')
        self.assertEqual(hall_item_success.status_code, status.HTTP_201_CREATED, hall_item_success.data)
        hall_submit_success = self.client.post(f'/api/v1/pos/orders/{hall_order.id}/submit/', {}, format='json')
        self.assertEqual(hall_submit_success.status_code, status.HTTP_200_OK, hall_submit_success.data)

        self.client.force_authenticate(self.hall_user)
        takeaway_item_forbidden = self.client.post(
            f'/api/v1/pos/orders/{takeaway_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(takeaway_item_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.takeaway_user)
        takeaway_item_success = self.client.post(
            f'/api/v1/pos/orders/{takeaway_order.id}/items/',
            item_payload,
            format='json',
        )
        self.assertEqual(takeaway_item_success.status_code, status.HTTP_201_CREATED, takeaway_item_success.data)
        takeaway_submit_success = self.client.post(f'/api/v1/pos/orders/{takeaway_order.id}/submit/', {}, format='json')
        self.assertEqual(takeaway_submit_success.status_code, status.HTTP_200_OK, takeaway_submit_success.data)

