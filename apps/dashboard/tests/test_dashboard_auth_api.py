from datetime import datetime

from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import CashShift, Payment
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.platform.models import RestaurantEntitlement
from apps.restaurants.models import CashDesk, Restaurant
from apps.sales.models import Order, OrderItem
from apps.users.models import Permission, Role, User
from common.utils.date import TASHKENT_TIMEZONE


class DashboardAuthApiTests(APITestCase):
    @classmethod
    def dt(cls, year, month, day, hour=0, minute=0):
        return datetime(year, month, day, hour, minute, tzinfo=TASHKENT_TIMEZONE)

    @classmethod
    def stamp_created_at(cls, instance, created_at):
        instance.__class__.objects.filter(pk=instance.pk).update(
            created_at=created_at,
            updated_at=created_at,
        )
        instance.refresh_from_db()
        return instance

    @classmethod
    def create_table_session(
        cls,
        *,
        restaurant,
        hall,
        table,
        opened_by=None,
        assigned_waiter=None,
        status=TableSession.Status.OPEN,
        guest_count=2,
        created_at,
        closed_at=None,
    ):
        session = TableSession.objects.create(
            restaurant=restaurant,
            hall=hall,
            table=table,
            opened_by=opened_by,
            assigned_waiter=assigned_waiter,
            status=status,
            guest_count=guest_count,
            closed_at=closed_at,
        )
        return cls.stamp_created_at(session, created_at)

    @classmethod
    def create_order(
        cls,
        *,
        restaurant,
        order_number,
        created_at,
        total,
        subtotal=None,
        status=Order.Status.CLOSED,
        channel=Order.Channel.HALL,
        opened_by=None,
        cashier=None,
        table_session=None,
        closed_at=None,
    ):
        order = Order.objects.create(
            restaurant=restaurant,
            order_number=order_number,
            status=status,
            channel=channel,
            opened_by=opened_by,
            cashier=cashier,
            table_session=table_session,
            subtotal=subtotal if subtotal is not None else total,
            total=total,
            closed_at=closed_at,
        )
        return cls.stamp_created_at(order, created_at)

    @classmethod
    def create_order_item(cls, *, order, catalog_item, quantity, unit_price, created_by=None):
        return OrderItem.objects.create(
            order=order,
            catalog_item=catalog_item,
            created_by=created_by or order.opened_by,
            quantity=quantity,
            unit_price=unit_price,
        )

    @classmethod
    def create_cash_shift(
        cls,
        *,
        cash_desk,
        opened_by,
        opened_at,
        status=CashShift.Status.OPEN,
        closed_at=None,
        cash_total=0,
        card_total=0,
        qr_total=0,
        refund_total=0,
        receipt_count=0,
        actual_closing_cash_amount=0,
        expected_closing_cash_amount=0,
        cash_difference_amount=0,
    ):
        shift = CashShift.objects.create(
            cash_desk=cash_desk,
            opened_by=opened_by,
            status=status,
            opened_at=opened_at,
            closed_at=closed_at,
            opening_cash_amount=0,
            actual_closing_cash_amount=actual_closing_cash_amount,
            expected_closing_cash_amount=expected_closing_cash_amount,
            cash_difference_amount=cash_difference_amount,
            cash_total=cash_total,
            card_total=card_total,
            qr_total=qr_total,
            refund_total=refund_total,
            receipt_count=receipt_count,
        )
        return cls.stamp_created_at(shift, opened_at)

    @classmethod
    def create_payment(
        cls,
        *,
        order,
        cash_desk,
        received_by,
        amount,
        method,
        paid_at,
        cash_shift=None,
    ):
        payment = Payment.objects.create(
            order=order,
            cash_desk=cash_desk,
            cash_shift=cash_shift,
            received_by=received_by,
            amount=amount,
            method=method,
            status=Payment.Status.SUCCEEDED,
            paid_at=paid_at,
        )
        return cls.stamp_created_at(payment, paid_at)

    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(
            name='Test restaurant',
            address='Tashkent city',
            currency='UZS',
        )
        cls.other_restaurant = Restaurant.objects.create(name='Other restaurant', currency='UZS')
        cls.entitlement = RestaurantEntitlement.objects.create(restaurant=cls.restaurant, is_active=True)
        cls.entitlement.permissions.set(Permission.objects.all())

        cls.dashboard_permission = Permission.objects.get(code='dashboard.view')
        cls.hall_permission = Permission.objects.get(code='halls.view')

        cls.owner_role = Role.objects.create(
            code='dashboard_owner_test',
            name='Dashboard owner',
            description='Dashboard owner',
            is_system=False,
        )
        cls.owner_role.permissions.set([cls.dashboard_permission])

        cls.staff_role = Role.objects.create(
            code='dashboard_staff_test',
            name='Dashboard staff',
            description='Dashboard staff',
            is_system=False,
        )
        cls.staff_role.permissions.set([cls.hall_permission])

        cls.waiter_role, _ = Role.objects.get_or_create(
            code='waiter',
            defaults={'name': 'Waiter', 'description': 'Waiter', 'is_system': True},
        )
        cls.cashier_role, _ = Role.objects.get_or_create(
            code='cashier',
            defaults={'name': 'Cashier', 'description': 'Cashier', 'is_system': True},
        )
        cls.manager_role, _ = Role.objects.get_or_create(
            code='manager',
            defaults={'name': 'Manager', 'description': 'Manager', 'is_system': True},
        )

        cls.entitlement.allowed_roles.set([cls.owner_role, cls.staff_role, cls.waiter_role, cls.cashier_role, cls.manager_role])

        cls.owner_user = User.objects.create_user(
            username='owner-user',
            password='secret123',
            full_name='Owner User',
            restaurant=cls.restaurant,
            role=cls.owner_role,
            is_staff=True,
            is_active=True,
        )
        cls.waiter_user = User.objects.create_user(
            username='waiter-user',
            password='secret123',
            full_name='Waiter User',
            restaurant=cls.restaurant,
            role=cls.waiter_role,
            is_staff=True,
            is_active=True,
        )
        cls.cashier_user = User.objects.create_user(
            username='cashier-user',
            password='secret123',
            full_name='Cashier User',
            restaurant=cls.restaurant,
            role=cls.cashier_role,
            is_staff=True,
            is_active=True,
        )
        cls.manager_user = User.objects.create_user(
            username='manager-user',
            password='secret123',
            full_name='Manager User',
            restaurant=cls.restaurant,
            role=cls.manager_role,
            is_staff=True,
            is_active=True,
        )
        cls.staff_user = User.objects.create_user(
            username='staff-user',
            password='secret123',
            full_name='Staff User',
            restaurant=cls.restaurant,
            role=cls.staff_role,
            is_staff=True,
            is_active=True,
        )
        cls.other_user = User.objects.create_user(
            username='other-user',
            password='secret123',
            full_name='Other User',
            restaurant=cls.other_restaurant,
            role=cls.owner_role,
            is_staff=True,
            is_active=True,
        )

        cls.zone = ZoneOrCabin.objects.create(restaurant=cls.restaurant, name='Main zone')
        cls.hall = Hall.objects.create(zone_or_cabin=cls.zone, name='Main hall')
        cls.table = DiningTable.objects.create(
            hall=cls.hall,
            zone=cls.zone,
            name='T1',
            table_number=1,
        )
        cls.cash_desk = CashDesk.objects.create(restaurant=cls.restaurant, name='Front cash desk')

        cls.other_zone = ZoneOrCabin.objects.create(restaurant=cls.other_restaurant, name='Other zone')
        cls.other_hall = Hall.objects.create(zone_or_cabin=cls.other_zone, name='Other hall')
        cls.other_table = DiningTable.objects.create(
            hall=cls.other_hall,
            zone=cls.other_zone,
            name='OT1',
            table_number=1,
        )
        cls.other_cash_desk = CashDesk.objects.create(restaurant=cls.other_restaurant, name='Other cash desk')

        cls.category = CatalogCategory.objects.create(restaurant=cls.restaurant, name='Fast food')
        cls.other_category = CatalogCategory.objects.create(restaurant=cls.other_restaurant, name='Other category')

        cls.burger = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Burger',
            price=18000,
        )
        cls.fries = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Fries',
            price=14000,
        )
        cls.pizza = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Pizza',
            price=54000,
        )
        cls.salad = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Salad',
            price=28000,
        )
        cls.steak = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Steak',
            price=48000,
        )
        cls.plov = CatalogItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.category,
            name='Plov',
            price=65000,
        )
        cls.other_item = CatalogItem.objects.create(
            restaurant=cls.other_restaurant,
            category=cls.other_category,
            name='Other item',
            price=99000,
        )

        cls.current_session = cls.create_table_session(
            restaurant=cls.restaurant,
            hall=cls.hall,
            table=cls.table,
            opened_by=cls.waiter_user,
            assigned_waiter=cls.waiter_user,
            status=TableSession.Status.OPEN,
            created_at=cls.dt(2026, 4, 7, 11, 30),
        )
        cls.month_session = cls.create_table_session(
            restaurant=cls.restaurant,
            hall=cls.hall,
            table=cls.table,
            opened_by=cls.waiter_user,
            assigned_waiter=cls.waiter_user,
            status=TableSession.Status.PENDING_PAYMENT,
            created_at=cls.dt(2026, 4, 3, 9, 15),
        )

        cls.shift_today = cls.create_cash_shift(
            cash_desk=cls.cash_desk,
            opened_by=cls.cashier_user,
            opened_at=cls.dt(2026, 4, 7, 9, 0),
            status=CashShift.Status.OPEN,
            cash_total=32000,
            receipt_count=1,
        )
        cls.shift_month = cls.create_cash_shift(
            cash_desk=cls.cash_desk,
            opened_by=cls.cashier_user,
            opened_at=cls.dt(2026, 4, 3, 8, 0),
            status=CashShift.Status.CLOSED,
            closed_at=cls.dt(2026, 4, 3, 23, 0),
            card_total=54000,
            receipt_count=1,
            actual_closing_cash_amount=0,
            expected_closing_cash_amount=0,
        )
        cls.shift_previous_month = cls.create_cash_shift(
            cash_desk=cls.cash_desk,
            opened_by=cls.cashier_user,
            opened_at=cls.dt(2026, 3, 15, 10, 0),
            status=CashShift.Status.CLOSED,
            closed_at=cls.dt(2026, 3, 15, 22, 0),
            qr_total=48000,
            receipt_count=1,
        )

        cls.order_today = cls.create_order(
            restaurant=cls.restaurant,
            order_number=101,
            created_at=cls.dt(2026, 4, 7, 12, 0),
            total=32000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.HALL,
            opened_by=cls.waiter_user,
            cashier=cls.cashier_user,
            table_session=cls.current_session,
            closed_at=cls.dt(2026, 4, 7, 12, 45),
        )
        cls.create_order_item(order=cls.order_today, catalog_item=cls.burger, quantity=1, unit_price=18000, created_by=cls.cashier_user)
        cls.create_order_item(order=cls.order_today, catalog_item=cls.fries, quantity=1, unit_price=14000, created_by=cls.cashier_user)
        cls.create_payment(
            order=cls.order_today,
            cash_desk=cls.cash_desk,
            cash_shift=cls.shift_today,
            received_by=cls.cashier_user,
            amount=32000,
            method=Payment.Method.CASH,
            paid_at=cls.dt(2026, 4, 7, 12, 46),
        )

        cls.order_month = cls.create_order(
            restaurant=cls.restaurant,
            order_number=102,
            created_at=cls.dt(2026, 4, 3, 13, 0),
            total=54000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.DELIVERY,
            opened_by=cls.waiter_user,
            cashier=cls.cashier_user,
            closed_at=cls.dt(2026, 4, 3, 13, 35),
        )
        cls.create_order_item(order=cls.order_month, catalog_item=cls.pizza, quantity=1, unit_price=54000, created_by=cls.cashier_user)
        cls.create_payment(
            order=cls.order_month,
            cash_desk=cls.cash_desk,
            cash_shift=cls.shift_month,
            received_by=cls.cashier_user,
            amount=54000,
            method=Payment.Method.CARD,
            paid_at=cls.dt(2026, 4, 3, 13, 36),
        )

        cls.order_previous_day = cls.create_order(
            restaurant=cls.restaurant,
            order_number=103,
            created_at=cls.dt(2026, 4, 6, 18, 0),
            total=28000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.TAKEAWAY,
            opened_by=cls.waiter_user,
            cashier=cls.cashier_user,
            closed_at=cls.dt(2026, 4, 6, 18, 20),
        )
        cls.create_order_item(order=cls.order_previous_day, catalog_item=cls.salad, quantity=1, unit_price=28000, created_by=cls.cashier_user)
        cls.create_payment(
            order=cls.order_previous_day,
            cash_desk=cls.cash_desk,
            received_by=cls.cashier_user,
            amount=28000,
            method=Payment.Method.CARD,
            paid_at=cls.dt(2026, 4, 6, 18, 21),
        )

        cls.order_previous_month = cls.create_order(
            restaurant=cls.restaurant,
            order_number=104,
            created_at=cls.dt(2026, 3, 15, 14, 0),
            total=48000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.ONLINE,
            opened_by=cls.waiter_user,
            cashier=cls.cashier_user,
            closed_at=cls.dt(2026, 3, 15, 14, 45),
        )
        cls.create_order_item(order=cls.order_previous_month, catalog_item=cls.steak, quantity=1, unit_price=48000)
        cls.create_payment(
            order=cls.order_previous_month,
            cash_desk=cls.cash_desk,
            cash_shift=cls.shift_previous_month,
            received_by=cls.cashier_user,
            amount=48000,
            method=Payment.Method.QR,
            paid_at=cls.dt(2026, 3, 15, 14, 46),
        )

        cls.order_previous_year = cls.create_order(
            restaurant=cls.restaurant,
            order_number=105,
            created_at=cls.dt(2025, 11, 20, 19, 0),
            total=65000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.HALL,
            opened_by=cls.waiter_user,
            cashier=cls.cashier_user,
            closed_at=cls.dt(2025, 11, 20, 19, 35),
        )
        cls.create_order_item(order=cls.order_previous_year, catalog_item=cls.plov, quantity=1, unit_price=65000)
        cls.create_payment(
            order=cls.order_previous_year,
            cash_desk=cls.cash_desk,
            received_by=cls.cashier_user,
            amount=65000,
            method=Payment.Method.CASH,
            paid_at=cls.dt(2025, 11, 20, 19, 36),
        )

        cls.open_order = cls.create_order(
            restaurant=cls.restaurant,
            order_number=106,
            created_at=cls.dt(2026, 4, 7, 19, 0),
            total=18000,
            status=Order.Status.OPEN,
            channel=Order.Channel.HALL,
            table_session=cls.current_session,
        )
        cls.create_order_item(order=cls.open_order, catalog_item=cls.burger, quantity=1, unit_price=18000)

        cls.other_shift = cls.create_cash_shift(
            cash_desk=cls.other_cash_desk,
            opened_by=cls.other_user,
            opened_at=cls.dt(2026, 4, 7, 9, 0),
            status=CashShift.Status.OPEN,
            cash_total=99000,
            receipt_count=1,
        )
        cls.other_order = cls.create_order(
            restaurant=cls.other_restaurant,
            order_number=201,
            created_at=cls.dt(2026, 4, 7, 12, 0),
            total=99000,
            status=Order.Status.CLOSED,
            channel=Order.Channel.DELIVERY,
            opened_by=cls.other_user,
            cashier=cls.other_user,
            table_session=cls.create_table_session(
                restaurant=cls.other_restaurant,
                hall=cls.other_hall,
                table=cls.other_table,
                opened_by=cls.other_user,
                assigned_waiter=cls.other_user,
                status=TableSession.Status.OPEN,
                created_at=cls.dt(2026, 4, 7, 11, 0),
            ),
            closed_at=cls.dt(2026, 4, 7, 12, 30),
        )
        cls.create_order_item(order=cls.other_order, catalog_item=cls.other_item, quantity=1, unit_price=99000)
        cls.create_payment(
            order=cls.other_order,
            cash_desk=cls.other_cash_desk,
            cash_shift=cls.other_shift,
            received_by=cls.other_user,
            amount=99000,
            method=Payment.Method.CARD,
            paid_at=cls.dt(2026, 4, 7, 12, 31),
        )

    def test_dashboard_login_returns_token_text_and_session(self):
        response = self.client.post(
            '/api/v1/dashboard/auth/login/',
            {'username': self.owner_user.username, 'password': 'secret123'},
            format='json',
            REMOTE_ADDR='192.0.2.10',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsInstance(response.data['token'], str)
        self.assertTrue(response.data['token'])
        self.assertEqual(response.data['user']['id'], str(self.owner_user.id))
        self.assertEqual(response.data['session']['surface'], 'dashboard')
        self.assertEqual(response.data['session']['status'], 'active')

    def test_dashboard_auth_me_requires_dashboard_permission(self):
        self.client.force_authenticate(self.owner_user)
        owner_response = self.client.get('/api/v1/dashboard/auth/me/')
        self.assertEqual(owner_response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.staff_user)
        staff_response = self.client.get('/api/v1/dashboard/auth/me/')
        self.assertEqual(staff_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_overview_requires_dashboard_permission(self):
        self.client.force_authenticate(self.staff_user)
        response = self.client.get('/api/v1/dashboard/overview/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_overview_requires_entitlement_permission(self):
        self.client.force_authenticate(self.owner_user)
        self.entitlement.permissions.remove(self.dashboard_permission)

        response = self.client.get('/api/v1/dashboard/overview/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_overview_returns_day_payload_shape(self):
        self.client.force_authenticate(self.owner_user)

        response = self.client.get('/api/v1/dashboard/overview/?period_type=day&date=2026-04-07')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['period']['period_type'], 'day')
        self.assertEqual(response.data['period']['start_date'], '2026-04-07')
        self.assertEqual(response.data['period']['end_date'], '2026-04-07')
        self.assertEqual(response.data['period']['comparison_start_date'], '2026-04-06')
        self.assertEqual(response.data['period']['comparison_end_date'], '2026-04-06')
        self.assertEqual(response.data['period']['chart_granularity'], 'hour')
        self.assertEqual(response.data['summary']['sales_total'], 32000)
        self.assertEqual(response.data['summary']['orders_count'], 1)
        self.assertEqual(response.data['summary']['open_checks'], 1)
        self.assertEqual(response.data['summary']['active_tables'], 1)
        self.assertEqual(len(response.data['revenue_series']), 24)
        self.assertEqual(len(response.data['previous_revenue_series']), 24)
        self.assertEqual(response.data['spotlight']['top_item']['item_name'], 'Burger')
        self.assertEqual(response.data['spotlight']['top_payment_method']['code'], 'cash')
        self.assertEqual(response.data['spotlight']['top_cashier']['items_count'], 2)
        self.assertIn('managers', response.data['staff_breakdown'])
        self.assertEqual(response.data['open_checks_snapshot']['count'], 1)
        self.assertEqual(response.data['open_checks_snapshot']['rows'][0]['order_number'], 106)
        self.assertEqual(response.data['cash_shift_snapshot']['open_count'], 1)
        self.assertEqual(response.data['cash_shift_snapshot']['rows'][0]['cash_total'], 32000)

    def test_dashboard_overview_returns_month_and_year_payload(self):
        self.client.force_authenticate(self.owner_user)

        month_response = self.client.get('/api/v1/dashboard/overview/?period_type=month&month=2026-04')
        year_response = self.client.get('/api/v1/dashboard/overview/?period_type=year&year=2026')

        self.assertEqual(month_response.status_code, status.HTTP_200_OK)
        self.assertEqual(year_response.status_code, status.HTTP_200_OK)

        self.assertEqual(month_response.data['period']['period_type'], 'month')
        self.assertEqual(month_response.data['period']['chart_granularity'], 'day')
        self.assertEqual(month_response.data['summary']['sales_total'], 114000)
        self.assertEqual(len(month_response.data['revenue_series']), 30)
        self.assertEqual(len(month_response.data['previous_revenue_series']), 30)

        self.assertEqual(year_response.data['period']['period_type'], 'year')
        self.assertEqual(year_response.data['period']['chart_granularity'], 'month')
        self.assertEqual(year_response.data['summary']['sales_total'], 162000)
        self.assertEqual(len(year_response.data['revenue_series']), 12)
        self.assertEqual(len(year_response.data['previous_revenue_series']), 12)

    def test_dashboard_overview_returns_range_payload(self):
        self.client.force_authenticate(self.owner_user)

        response = self.client.get(
            '/api/v1/dashboard/overview/?period_type=range&start_date=2026-04-01&end_date=2026-04-07'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['period']['period_type'], 'range')
        self.assertEqual(response.data['period']['start_date'], '2026-04-01')
        self.assertEqual(response.data['period']['end_date'], '2026-04-07')
        self.assertEqual(response.data['period']['comparison_start_date'], '2026-03-25')
        self.assertEqual(response.data['period']['comparison_end_date'], '2026-03-31')
        self.assertEqual(response.data['period']['chart_granularity'], 'day')
        self.assertEqual(response.data['summary']['sales_total'], 114000)
        self.assertEqual(response.data['summary']['orders_count'], 3)
        self.assertEqual(response.data['summary']['open_checks'], 1)
        self.assertEqual(response.data['summary']['active_tables'], 2)
        self.assertEqual(len(response.data['revenue_series']), 7)
        self.assertEqual(len(response.data['previous_revenue_series']), 7)
        self.assertEqual(response.data['spotlight']['top_payment_method']['code'], 'card')
        self.assertEqual(response.data['cash_shift_snapshot']['open_count'], 1)

    def test_dashboard_detail_endpoints_are_paginated_and_owner_scoped(self):
        self.client.force_authenticate(self.owner_user)

        open_checks_response = self.client.get('/api/v1/dashboard/open-checks/?period_type=day&date=2026-04-07')
        top_items_response = self.client.get('/api/v1/dashboard/top-items/?period_type=month&month=2026-04')
        staff_response = self.client.get('/api/v1/dashboard/staff/?period_type=day&date=2026-04-07&role=cashier')
        shifts_response = self.client.get('/api/v1/dashboard/shifts/?period_type=month&month=2026-04')

        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertEqual(top_items_response.status_code, status.HTTP_200_OK)
        self.assertEqual(staff_response.status_code, status.HTTP_200_OK)
        self.assertEqual(shifts_response.status_code, status.HTTP_200_OK)

        self.assertEqual(open_checks_response.data['total'], 1)
        self.assertEqual(open_checks_response.data['data'][0]['order_number'], 106)
        self.assertEqual(top_items_response.data['data'][0]['item_name'], 'Pizza')
        self.assertEqual(staff_response.data['data'][0]['user_name'], 'Cashier User')
        self.assertEqual(staff_response.data['data'][0]['sales_total'], 32000)
        self.assertEqual(staff_response.data['data'][0]['items_count'], 2)
        self.assertEqual(shifts_response.data['total'], 2)
        self.assertEqual(shifts_response.data['data'][0]['cash_desk_name'], 'Front cash desk')

    def test_dashboard_detail_endpoints_support_range_filters(self):
        self.client.force_authenticate(self.owner_user)

        open_checks_response = self.client.get(
            '/api/v1/dashboard/open-checks/?period_type=range&start_date=2026-04-01&end_date=2026-04-07'
        )
        top_items_response = self.client.get(
            '/api/v1/dashboard/top-items/?period_type=range&start_date=2026-04-01&end_date=2026-04-07'
        )
        staff_response = self.client.get(
            '/api/v1/dashboard/staff/?period_type=range&start_date=2026-04-01&end_date=2026-04-07&role=cashier'
        )
        shifts_response = self.client.get(
            '/api/v1/dashboard/shifts/?period_type=range&start_date=2026-04-01&end_date=2026-04-07'
        )

        self.assertEqual(open_checks_response.status_code, status.HTTP_200_OK)
        self.assertEqual(top_items_response.status_code, status.HTTP_200_OK)
        self.assertEqual(staff_response.status_code, status.HTTP_200_OK)
        self.assertEqual(shifts_response.status_code, status.HTTP_200_OK)

        self.assertEqual(open_checks_response.data['total'], 1)
        self.assertEqual(open_checks_response.data['data'][0]['order_number'], 106)
        self.assertEqual(top_items_response.data['data'][0]['item_name'], 'Pizza')
        self.assertEqual(staff_response.data['data'][0]['user_name'], 'Cashier User')
        self.assertEqual(staff_response.data['data'][0]['sales_total'], 114000)
        self.assertEqual(staff_response.data['data'][0]['items_count'], 4)
        self.assertEqual(shifts_response.data['total'], 2)

    def test_dashboard_detail_endpoints_require_dashboard_permission(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.get('/api/v1/dashboard/open-checks/?period_type=day&date=2026-04-07')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
