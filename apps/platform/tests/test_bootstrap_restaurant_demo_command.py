from datetime import timedelta

from django.core.management import call_command
from django.db.models import Max
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import CashShift, Payment, Receipt
from apps.floor.models import DiningTable, Hall
from apps.platform.models import Tariff
from apps.platform.services import add_billing_period
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.users.models import User


class BootstrapRestaurantDemoCommandTests(TestCase):
    def test_command_seeds_rich_two_restaurant_demo_dataset(self):
        call_command('run_seeder')

        self.assertTrue(User.objects.filter(username='admin').exists())
        self.assertTrue(User.objects.filter(username='superadmin').exists())
        self.assertTrue(User.objects.filter(role__code='business_partner').exists())

        tariffs = Tariff.objects.filter(name__in=['Restaurant tarifi', 'Fast food tarifi']).order_by('name')
        self.assertEqual(tariffs.count(), 2)

        restaurant = Restaurant.objects.get(name='Postcode Restaurant')
        fast_food = Restaurant.objects.get(name='Postcode Fast Food')

        self.assertEqual(restaurant.entitlement.tariff.name, 'Restaurant tarifi')
        self.assertEqual(fast_food.entitlement.tariff.name, 'Fast food tarifi')
        self.assertEqual(restaurant.entitlement.starts_on, timezone.localdate())
        self.assertEqual(fast_food.entitlement.starts_on, timezone.localdate())
        self.assertEqual(
            restaurant.entitlement.expires_on,
            add_billing_period(restaurant.entitlement.starts_on, restaurant.entitlement.billing_period),
        )
        self.assertEqual(
            fast_food.entitlement.expires_on,
            add_billing_period(fast_food.entitlement.starts_on, fast_food.entitlement.billing_period),
        )

        self.assertEqual(restaurant.zones.count(), 3)
        self.assertEqual(Hall.objects.filter(zone_or_cabin__restaurant=restaurant).count(), 5)
        self.assertEqual(restaurant.catalog_categories.count(), 7)
        self.assertGreaterEqual(restaurant.catalog_items.count(), 24)
        self.assertEqual(restaurant.catalog_items.exclude(mxik_code='').count(), restaurant.catalog_items.count())
        self.assertEqual(restaurant.catalog_categories.exclude(image_url='').count(), restaurant.catalog_categories.count())

        self.assertFalse(fast_food.zones.exists())
        self.assertEqual(fast_food.catalog_categories.count(), 7)
        self.assertGreaterEqual(fast_food.catalog_items.count(), 19)
        self.assertEqual(fast_food.catalog_items.exclude(mxik_code='').count(), fast_food.catalog_items.count())
        self.assertEqual(fast_food.catalog_categories.exclude(image_url='').count(), fast_food.catalog_categories.count())

        self.assertEqual(restaurant.table_sessions.count(), Order.objects.filter(restaurant=restaurant, channel=Order.Channel.HALL).count())
        self.assertEqual(DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant).count(), 18)
        self.assertEqual(
            DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant, status=DiningTable.Status.OCCUPIED).count(),
            2,
        )
        self.assertEqual(
            DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant, status=DiningTable.Status.RESERVED).count(),
            1,
        )
        self.assertEqual(
            DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant, status=DiningTable.Status.BLOCKED).count(),
            1,
        )

        self.assertTrue(Order.objects.filter(restaurant=restaurant, status=Order.Status.CLOSED).exists())
        self.assertTrue(Order.objects.filter(restaurant=restaurant).exclude(status=Order.Status.CLOSED).exists())
        self.assertTrue(Order.objects.filter(restaurant=fast_food, status=Order.Status.CLOSED).exists())
        self.assertTrue(Order.objects.filter(restaurant=fast_food).exclude(status=Order.Status.CLOSED).exists())
        self.assertFalse(Order.objects.filter(restaurant=fast_food, channel=Order.Channel.HALL).exists())

        earliest_restaurant_order = Order.objects.filter(restaurant=restaurant).order_by('created_at').first()
        earliest_fastfood_order = Order.objects.filter(restaurant=fast_food).order_by('created_at').first()
        self.assertGreaterEqual(
            (timezone.localdate() - timezone.localtime(earliest_restaurant_order.created_at).date()).days,
            59,
        )
        self.assertGreaterEqual(
            (timezone.localdate() - timezone.localtime(earliest_fastfood_order.created_at).date()).days,
            59,
        )

        payment_methods = set(Payment.objects.values_list('method', flat=True))
        self.assertTrue({Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR}.issubset(payment_methods))
        self.assertEqual(Payment.objects.count(), Receipt.objects.count())

        restaurant_shifts = CashShift.objects.filter(cash_desk__restaurant=restaurant)
        fastfood_shifts = CashShift.objects.filter(cash_desk__restaurant=fast_food)
        self.assertTrue(restaurant_shifts.filter(status=CashShift.Status.CLOSED).exists())
        self.assertTrue(restaurant_shifts.filter(status=CashShift.Status.OPEN).exists())
        self.assertTrue(fastfood_shifts.filter(status=CashShift.Status.CLOSED).exists())
        self.assertTrue(fastfood_shifts.filter(status=CashShift.Status.OPEN).exists())

        self.assertEqual(
            restaurant.last_order_number,
            Order.objects.filter(restaurant=restaurant).aggregate(max_number=Max('order_number'))['max_number'],
        )
        self.assertEqual(
            fast_food.last_order_number,
            Order.objects.filter(restaurant=fast_food).aggregate(max_number=Max('order_number'))['max_number'],
        )

        self.assertGreaterEqual(Order.objects.filter(restaurant=restaurant).count(), 210)
        self.assertGreaterEqual(Order.objects.filter(restaurant=fast_food).count(), 135)
        self.assertGreaterEqual(Payment.objects.filter(order__restaurant=restaurant).count(), 200)
        self.assertGreaterEqual(Payment.objects.filter(order__restaurant=fast_food).count(), 130)

        self.assertTrue(
            Payment.objects.filter(order__restaurant=restaurant, paid_at__gte=timezone.now() - timedelta(days=1)).exists()
        )
