from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule

from apps.platform.models import BusinessPartner, RestaurantBalanceTransaction, RestaurantEntitlement
from apps.platform.services import create_restaurant_top_up
from apps.platform.services import EXPIRY_SCHEDULE_FUNC, EXPIRY_SCHEDULE_NAME, ensure_expiry_schedule, expire_restaurant_entitlements
from apps.restaurants.models import Restaurant


class RestaurantSubscriptionExpiryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        partner = BusinessPartner.objects.create(
            inn='987654321',
            company_name='Expiry Partner',
            legal_name='Expiry Partner LLC',
            status=BusinessPartner.Status.ACTIVE,
        )
        cls.expired_restaurant = Restaurant.objects.create(
            business_partner=partner,
            name='Expired Restaurant',
            legal_name='Expired Restaurant LLC',
            is_active=True,
            activated_at=timezone.now(),
        )
        cls.active_restaurant = Restaurant.objects.create(
            business_partner=partner,
            name='Active Restaurant',
            legal_name='Active Restaurant LLC',
            is_active=True,
            activated_at=timezone.now(),
        )
        cls.renewable_restaurant = Restaurant.objects.create(
            business_partner=partner,
            name='Renewable Restaurant',
            legal_name='Renewable Restaurant LLC',
            is_active=True,
            activated_at=timezone.now(),
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.expired_restaurant,
            is_active=True,
            starts_on=date(2026, 3, 1),
            expires_on=date(2026, 4, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
            monthly_price=100,
            yearly_price=1000,
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.active_restaurant,
            is_active=True,
            starts_on=date(2026, 4, 1),
            expires_on=date(2026, 5, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
            monthly_price=100,
            yearly_price=1000,
        )
        RestaurantEntitlement.objects.create(
            restaurant=cls.renewable_restaurant,
            is_active=True,
            starts_on=date(2026, 3, 1),
            expires_on=date(2026, 4, 1),
            billing_period=RestaurantEntitlement.BillingPeriod.MONTHLY,
            monthly_price=100,
            yearly_price=1000,
        )
        create_restaurant_top_up(restaurant=cls.renewable_restaurant, amount='150.00')

    def test_expire_restaurant_entitlements_handles_expired_rows(self):
        with patch('apps.platform.services.restaurant_subscriptions.timezone.localdate', return_value=date(2026, 4, 7)):
            expired_count = expire_restaurant_entitlements()

        self.assertEqual(expired_count, 2)
        self.expired_restaurant.refresh_from_db()
        self.active_restaurant.refresh_from_db()
        self.renewable_restaurant.refresh_from_db()

        self.assertFalse(self.expired_restaurant.is_active)
        self.assertFalse(self.expired_restaurant.entitlement.is_active)
        self.assertIsNotNone(self.expired_restaurant.deactivated_at)
        self.assertTrue(self.active_restaurant.is_active)
        self.assertTrue(self.active_restaurant.entitlement.is_active)
        self.assertTrue(self.renewable_restaurant.is_active)
        self.assertTrue(self.renewable_restaurant.entitlement.is_active)

    def test_expire_restaurant_entitlements_creates_renewal_charge_when_balance_is_enough(self):
        with patch('apps.platform.services.restaurant_subscriptions.timezone.localdate', return_value=date(2026, 4, 7)):
            expire_restaurant_entitlements()

        self.renewable_restaurant.refresh_from_db()

        self.assertEqual(self.renewable_restaurant.entitlement.starts_on, date(2026, 4, 7))
        self.assertEqual(self.renewable_restaurant.entitlement.expires_on, date(2026, 5, 7))
        renewal_charge = RestaurantBalanceTransaction.objects.filter(
            restaurant=self.renewable_restaurant,
            kind=RestaurantBalanceTransaction.Kind.RENEWAL_CHARGE,
        ).get()
        self.assertEqual(renewal_charge.amount, -100)
        self.assertEqual(renewal_charge.balance_after, 50)
        self.assertEqual(renewal_charge.period_start, date(2026, 4, 7))
        self.assertEqual(renewal_charge.period_end, date(2026, 5, 7))

    def test_ensure_expiry_schedule_is_idempotent(self):
        ensure_expiry_schedule()
        ensure_expiry_schedule()

        schedules = Schedule.objects.filter(name=EXPIRY_SCHEDULE_NAME, func=EXPIRY_SCHEDULE_FUNC)

        self.assertEqual(schedules.count(), 1)
        self.assertEqual(schedules.first().schedule_type, Schedule.HOURLY)
