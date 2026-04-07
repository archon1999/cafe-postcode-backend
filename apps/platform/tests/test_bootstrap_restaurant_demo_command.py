from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.users.models import User
from apps.sales.models import Order
from apps.restaurants.models import Restaurant
from apps.platform.models import Tariff
from apps.platform.services import add_billing_period


class BootstrapRestaurantDemoCommandTests(TestCase):
    def test_command_seeds_two_tariffs_two_restaurants_and_takeaway_only_fast_food_history(self):
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
        self.assertIsNotNone(restaurant.activated_at)
        self.assertIsNotNone(fast_food.activated_at)
        self.assertEqual(restaurant.entitlement.starts_on, timezone.localdate())
        self.assertEqual(fast_food.entitlement.starts_on, timezone.localdate())
        self.assertEqual(restaurant.entitlement.billing_period, 'monthly')
        self.assertEqual(fast_food.entitlement.billing_period, 'monthly')
        self.assertEqual(
            restaurant.entitlement.expires_on,
            add_billing_period(restaurant.entitlement.starts_on, restaurant.entitlement.billing_period),
        )
        self.assertEqual(
            fast_food.entitlement.expires_on,
            add_billing_period(fast_food.entitlement.starts_on, fast_food.entitlement.billing_period),
        )
        self.assertTrue(restaurant.zones.exists())
        self.assertFalse(fast_food.zones.exists())

        self.assertEqual(
            User.objects.filter(
                restaurant_profile__restaurant=restaurant,
                role__code__in=('restaurant_admin', 'fast_food_admin'),
            ).first().role.code,
            'restaurant_admin',
        )
        self.assertEqual(
            User.objects.filter(
                restaurant_profile__restaurant=fast_food,
                role__code__in=('restaurant_admin', 'fast_food_admin'),
            ).first().role.code,
            'fast_food_admin',
        )

        restaurant_item_codes = set(restaurant.catalog_items.values_list('mxik_code', flat=True))
        fast_food_item_codes = set(fast_food.catalog_items.values_list('mxik_code', flat=True))
        self.assertNotEqual(restaurant_item_codes, fast_food_item_codes)
        self.assertTrue({'01006001002000000', '00206001002000000', '00708002001000000'}.issubset(restaurant_item_codes))
        self.assertTrue({'00701001001000000', '02103001004000000', '02202002006000000'}.issubset(fast_food_item_codes))
        self.assertTrue(restaurant.catalog_categories.exclude(image_url='').exists())
        self.assertTrue(fast_food.catalog_categories.exclude(image_url='').exists())

        self.assertTrue(Order.objects.filter(restaurant=restaurant, channel=Order.Channel.HALL).exists())
        self.assertFalse(
            Order.objects.filter(restaurant=fast_food).exclude(channel=Order.Channel.TAKEAWAY).exists()
        )

