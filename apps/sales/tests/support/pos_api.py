from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.users.models import Permission, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.billing.models import CashShift
from apps.restaurants.models import DistributionPoint, PrepStation, Restaurant
from apps.platform.models import RestaurantEntitlement, Tariff


class PosTestDataMixin:
    permission_codes = (
        'pos_halls.view',
        'pos_tables.manage',
        'pos_table_menu.view',
        'pos_takeaway_menu.view',
        'pos_kitchen_orders.view',
        'pos_kitchen_orders.update',
        'pos_open_checks.view',
        'pos_payments.create',
        'pos_table_reservations.manage',
        'reports.view',
    )

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.restaurant = Restaurant.objects.create(
            name='Test restaurant',
            service_fee_percent=10,
            legal_name='Test Restaurant LLC',
            tax_number='123456789',
        )
        cls.branch = cls.restaurant
        cls.permissions = []
        for code in cls.permission_codes:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={'name': code, 'description': f'{code} permission'},
            )
            cls.permissions.append(permission)
        cls.role = Role.objects.get_or_create(
            code='pos-test-role',
            defaults={'name': 'POS Test Role', 'description': 'POS test role', 'is_system': False},
        )[0]
        cls.role.permissions.set(cls.permissions)
        cls.tariff = Tariff.objects.create(
            name='POS Test Tariff',
            description='Tariff for POS test data',
            monthly_price=0,
            yearly_price=0,
            is_active=True,
        )
        cls.tariff.permissions.set(cls.permissions)
        cls.tariff.allowed_roles.set([cls.role])
        cls.entitlement = RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            tariff=cls.tariff,
            is_active=True,
            is_custom=False,
        )
        cls.user = User.objects.create_user(
            username='pos-test-user',
            password='secret123',
            full_name='POS Test User',
            restaurant=cls.restaurant,
            role=cls.role,
            is_staff=True,
        )
        cls.zone = ZoneOrCabin.objects.create(
            restaurant=cls.restaurant,
            name='Asosiy zona',
            sort_order=1,
        )
        cls.hall = Hall.objects.create(
            zone_or_cabin=cls.zone,
            name='Asosiy zal',
            grid_columns=8,
            sort_order=1,
        )
        cls.table = DiningTable.objects.create(
            hall=cls.hall,
            name='Asosiy zal 1',
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
        cls.prep_station = PrepStation.objects.create(
            restaurant=cls.restaurant,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        cls.cash_desk = cls.restaurant.cash_desks.create(
            name='Main cashier',
            location='Front desk',
            enabled_payment_methods=['cash', 'card', 'qr'],
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.restaurant,
            name='Taomlar',
            mxik_code='10000000000000001',
            mxik_name='Taomlar',
        )
        cls.catalog_item = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Osh',
            prep_station=cls.prep_station,
            price=30000,
        )
        cls.hall_distribution = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Hall orders',
            kind=DistributionPoint.Kind.HALL,
            assigned_hall=cls.hall,
        )
        cls.takeaway_distribution = DistributionPoint.objects.create(
            restaurant=cls.restaurant,
            name='Takeaway',
            kind=DistributionPoint.Kind.TAKEAWAY,
        )

    @classmethod
    def create_table_session(cls, *, status=TableSession.Status.OPEN, guest_count=4, table=None, opened_by=None):
        table = table or cls.table
        opened_by = opened_by or cls.user
        return TableSession.objects.create(
            restaurant=cls.restaurant,
            hall=table.hall,
            table=table,
            opened_by=opened_by,
            assigned_waiter=opened_by,
            guest_count=guest_count,
            status=status,
        )

    @classmethod
    def create_cash_shift(cls, *, cash_desk=None, opened_by=None, opening_cash_amount=0):
        return CashShift.objects.create(
            cash_desk=cash_desk or cls.cash_desk,
            opened_by=opened_by or cls.user,
            opened_at=timezone.now(),
            opening_cash_amount=opening_cash_amount,
        )


class PosTestCase(PosTestDataMixin, TestCase):
    pass


class PosAPITestCase(PosTestDataMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def create_order_via_api(self, payload):
        response = self.client.post('/api/v1/pos/sales/orders/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def add_item_via_api(self, order_id, *, catalog_item=None, quantity=1, note=''):
        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order_id}/items/',
            {
                'catalog_item': str((catalog_item or self.catalog_item).id),
                'quantity': quantity,
                'note': note,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def submit_order_via_api(self, order_id):
        response = self.client.post(f'/api/v1/pos/sales/orders/{order_id}/submit/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def pay_order_via_api(self, order_id, *, method='cash', amount=0):
        if not CashShift.objects.filter(cash_desk__restaurant=self.restaurant, opened_by=self.user, status=CashShift.Status.OPEN).exists():
            self.create_cash_shift(opening_cash_amount=0)
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{order_id}/pay/',
            {'method': method, 'amount': amount},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def open_shift_via_api(self, *, cash_desk_id=None, opening_cash_amount=0, notes_open=''):
        payload = {'opening_cash_amount': opening_cash_amount, 'notes_open': notes_open}
        if cash_desk_id is not None:
            payload['cash_desk_id'] = str(cash_desk_id)
        response = self.client.post('/api/v1/pos/billing/shifts/open/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def close_shift_via_api(self, *, actual_closing_cash_amount, notes_close=''):
        response = self.client.post(
            '/api/v1/pos/billing/shifts/current/close/',
            {'actual_closing_cash_amount': actual_closing_cash_amount, 'notes_close': notes_close},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def refund_payment_via_api(self, payment_id, *, reason=''):
        response = self.client.post(f'/api/v1/pos/billing/{payment_id}/refund/', {'reason': reason}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def reprint_receipt_via_api(self, receipt_id):
        response = self.client.post(f'/api/v1/pos/billing/receipts/{receipt_id}/reprint/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

