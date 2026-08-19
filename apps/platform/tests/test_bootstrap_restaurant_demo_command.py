from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Max
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import CashShift, Payment, Receipt
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, ZoneOrCabin
from apps.integrations.models import IntegrationConfig
from apps.platform.models import BusinessPartner, Tariff
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.users.models import User


class BootstrapRestaurantDemoCommandTests(TestCase):
    @override_settings(DJANGO_PRODUCTION=True)
    def test_command_is_hard_blocked_in_production(self):
        with self.assertRaisesMessage(CommandError, 'run_seeder is disabled'):
            call_command('run_seeder')

    def test_command_reuses_legacy_demo_restaurant_without_delete(self):
        legacy_restaurant = Restaurant.objects.create(
            name='Postcode Restaurant',
            legal_name='Legacy Demo',
            tax_number='309999001',
            phone='+998900000001',
            address='Legacy address',
        )
        zone = ZoneOrCabin.objects.create(restaurant=legacy_restaurant, name='Legacy zone')
        Hall.objects.create(zone_or_cabin=zone, name='Legacy hall')
        category = CatalogCategory.objects.create(restaurant=legacy_restaurant, name='Legacy category')
        CatalogItem.objects.create(restaurant=legacy_restaurant, category=category, name='Legacy item', price=1000)

        call_command('run_seeder')

        legacy_restaurant.refresh_from_db()
        self.assertEqual(legacy_restaurant.name, 'GULISTON RESTAURANT')
        self.assertEqual(legacy_restaurant.tax_number, '311926992')
        self.assertEqual(legacy_restaurant.business_partner.inn, '310162774')
        self.assertFalse(Restaurant.objects.filter(name='Postcode Restaurant').exists())
        self.assertGreater(legacy_restaurant.zones.count(), 0)
        self.assertGreater(legacy_restaurant.catalog_categories.count(), 0)
        self.assertGreater(legacy_restaurant.catalog_items.count(), 0)

    def test_command_seeds_rich_two_restaurant_demo_dataset(self):
        call_command('run_seeder')

        self.assertTrue(User.objects.filter(username='admin').exists())
        self.assertTrue(User.objects.filter(username='superadmin').exists())
        self.assertTrue(User.objects.filter(role__code='business_partner').exists())
        self.assertFalse(User.objects.filter(role__code='owner').exists())

        tariffs = Tariff.objects.filter(name__in=['Restaurant tarifi', 'Fast food tarifi']).order_by('name')
        self.assertEqual(tariffs.count(), 2)

        partner = BusinessPartner.objects.get(inn='310162774')
        restaurant = Restaurant.objects.get(name='GULISTON RESTAURANT')
        fast_food = Restaurant.objects.get(name='BROCCOLI FOOD')
        restaurant_printer = IntegrationConfig.objects.get(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
        )

        self.assertEqual(restaurant.entitlement.tariff.name, 'Restaurant tarifi')
        self.assertEqual(fast_food.entitlement.tariff.name, 'Fast food tarifi')
        self.assertIn('dashboard.view', restaurant.entitlement.get_effective_permission_codes())
        self.assertIn('dashboard.view', fast_food.entitlement.get_effective_permission_codes())
        self.assertTrue(restaurant_printer.is_enabled)
        self.assertEqual(restaurant_printer.settings.get('printer_name'), 'POS-80 USB')
        self.assertFalse(
            IntegrationConfig.objects.filter(
                restaurant=fast_food,
                kind=IntegrationConfig.Kind.PRINTER,
                provider__in=('mock-printer', 'qz-tray'),
            ).exists()
        )
        self.assertEqual(partner.company_name, 'ABSOLYUT POWER SYSTEM MCHJ')
        self.assertEqual(partner.director_name, 'Jurayev Akmaljon Ruzibayevich')
        self.assertEqual(restaurant.tax_number, '311926992')
        self.assertEqual(fast_food.tax_number, '304459113')
        self.assertTrue(User.objects.filter(restaurant_profile__restaurant=restaurant, role__code='restaurant_admin').exists())
        self.assertTrue(User.objects.filter(restaurant_profile__restaurant=fast_food, role__code='fast_food_admin').exists())
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
