from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from apps.integrations.models import IntegrationConfig
from apps.platform.models import BusinessPartner, RestaurantEntitlement
from apps.platform.services import create_restaurant_top_up
from apps.restaurants.models import Restaurant
from apps.users.models import EmployeeProfile, Role, User


class RestaurantBalanceAdminApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.business_partner_role = Role.objects.get(code='business_partner')
        cls.restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        cls.waiter_role = Role.objects.get(code='waiter')

        cls.partner = BusinessPartner.objects.create(
            inn='456789123',
            company_name='Partner Detail LLC',
            legal_name='Partner Detail LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.partner_user = User.objects.create_user(
            username='partner-detail-owner',
            password='secret123',
            full_name='Partner Detail Owner',
            role=cls.business_partner_role,
            business_partner=cls.partner,
            is_staff=True,
            is_active=True,
        )
        cls.restaurant = Restaurant.objects.create(
            business_partner=cls.partner,
            name='Balance Restaurant',
            legal_name='Balance Restaurant LLC',
            tax_number='301234567',
            phone='+998901112233',
            address='Tashkent',
            is_active=True,
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.restaurant,
            is_active=True,
            starts_on=date(2026, 4, 1),
            expires_on=date(2026, 5, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
            monthly_price=1200,
            yearly_price=12000,
        )
        IntegrationConfig.objects.create(
            restaurant=cls.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='soliq-ofd',
            mode=IntegrationConfig.Mode.LIVE,
            is_enabled=True,
            settings={
                'terminal_id': 'TERM-1',
                'cashbox_id': 'CASHBOX-1',
                'tax_number': '301234567',
                'endpoint_url': 'https://soliq.example/api',
            },
        )

        cls.admin_user = User.objects.create_user(
            username='balance-admin',
            password='secret123',
            full_name='Balance Admin',
            role=cls.restaurant_admin_role,
            restaurant=cls.restaurant,
            is_staff=True,
            is_active=True,
        )
        cls.waiter_user = User.objects.create_user(
            username='balance-waiter',
            password='secret123',
            full_name='Balance Waiter',
            role=cls.waiter_role,
            restaurant=cls.restaurant,
            is_staff=True,
            is_active=True,
        )

        cls.inactive_user = User.objects.create_user(
            username='inactive-waiter',
            password='secret123',
            full_name='Inactive Waiter',
            role=cls.waiter_role,
            restaurant=cls.restaurant,
            is_staff=True,
            is_active=True,
        )
        cls.inactive_user.employee_profile.employment_status = EmployeeProfile.EmploymentStatus.INACTIVE
        cls.inactive_user.employee_profile.save(update_fields=['employment_status'])

        create_restaurant_top_up(
            restaurant=cls.restaurant,
            amount='5000.00',
            performed_by=cls.partner_user,
            note='Initial top-up',
        )

    def setUp(self):
        self.client.force_authenticate(self.partner_user)

    def test_restaurant_detail_returns_active_users_soliq_summary_and_balance(self):
        response = self.client.get(f'/api/v1/admin/restaurants/{self.restaurant.id}/detail/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['name'], self.restaurant.name)
        self.assertEqual({item['username'] for item in response.data['active_users']}, {'balance-admin', 'balance-waiter'})
        self.assertEqual(response.data['soliq_integration']['provider'], 'soliq-ofd')
        self.assertEqual(response.data['soliq_integration']['terminal_id'], 'TERM-1')
        self.assertEqual(response.data['balance']['current_balance'], '5000.00')
        self.assertEqual(response.data['balance']['next_charge_amount'], '1200.00')
        self.assertEqual(response.data['balance']['next_period_status'], 'active')
        self.assertIsNotNone(response.data['balance']['last_top_up_at'])

    def test_balance_transactions_endpoint_returns_paginated_history(self):
        second_top_up = create_restaurant_top_up(
            restaurant=self.restaurant,
            amount='700.00',
            performed_by=self.partner_user,
            note='Second top-up',
        )

        response = self.client.get(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/balance-transactions/',
            {'pageSize': 10},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['data'][0]['id'], str(second_top_up.id))
        self.assertEqual(response.data['data'][0]['performed_by']['username'], self.partner_user.username)

    def test_top_up_endpoint_creates_transaction_with_balance_after(self):
        response = self.client.post(
            f'/api/v1/admin/platform/restaurants/{self.restaurant.id}/top-up/',
            {'amount': '3500.00', 'note': 'Manual top-up'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['kind'], 'top_up')
        self.assertEqual(response.data['amount'], '3500.00')
        self.assertEqual(response.data['balance_after'], '8500.00')
        self.assertEqual(response.data['performed_by']['username'], self.partner_user.username)
