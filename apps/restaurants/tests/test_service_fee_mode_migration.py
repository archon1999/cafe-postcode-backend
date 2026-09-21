from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.restaurants.models import Restaurant
from common.service_fees import calculate_hourly_service_fee, calculate_service_fee_components


class HourlySettingsMigrationTests(TestCase):
    def test_migration_preserves_tariffs_and_existing_session_snapshots(self):
        settings = dict(service_fee_enabled=True, service_fee_mode='hourly', service_fee_hourly_rate=100000)
        restaurant = Restaurant.objects.create(name='Legacy hourly', **settings)
        zone = ZoneOrCabin.objects.create(restaurant=restaurant, name='Zone')
        hall = Hall.objects.create(zone_or_cabin=zone, name='Hall', **settings)
        table = DiningTable.objects.create(hall=hall, name='Table', table_number='1', **settings)
        session = TableSession.objects.create(restaurant=restaurant, hall=hall, table=table)
        original_snapshot = session.service_fee_snapshot
        migration = import_module('apps.restaurants.migrations.0032_hourly_service_fees_to_formulas')
        migration.migrate_hourly_settings(apps, SimpleNamespace(connection=connection))
        start = timezone.now()
        for row in (restaurant, hall, table):
            row.refresh_from_db()
            self.assertEqual(row.service_fee_mode, 'formula')
            for elapsed, billable in ((0, 60), (30, 60), (64, 60), (65, 65), (90, 90)):
                components = calculate_service_fee_components(
                    snapshot=[{'scope': 'table', 'mode': 'formula', 'formula': row.service_fee_formula}],
                    subtotal=10000, started_at=start, ended_at=start + timedelta(minutes=elapsed),
                )
                self.assertEqual(components[0]['amount'], calculate_hourly_service_fee(hourly_rate=100000, minutes=billable))
        session.refresh_from_db()
        self.assertEqual(session.service_fee_snapshot, original_snapshot)
        migration.restore_hourly_settings(apps, SimpleNamespace(connection=connection))
        for row in (restaurant, hall, table):
            row.refresh_from_db()
            self.assertEqual(row.service_fee_mode, 'hourly')
            self.assertEqual(row.service_fee_hourly_rate, 100000)
            self.assertEqual(row.service_fee_formula, {})

    def test_reverse_preflights_all_scopes_and_preserves_modified_formulas(self):
        migration = import_module('apps.restaurants.migrations.0032_hourly_service_fees_to_formulas')
        restaurant = Restaurant.objects.create(name='Rollback', service_fee_mode='hourly', service_fee_hourly_rate=100000)
        zone = ZoneOrCabin.objects.create(restaurant=restaurant, name='Zone')
        hall = Hall.objects.create(zone_or_cabin=zone, name='Edited', service_fee_mode='formula',
                                   service_fee_formula={'source': '50000'})
        migration.migrate_hourly_settings(apps, SimpleNamespace(connection=connection))
        with self.assertRaisesRegex(RuntimeError, 'custom or modified formula'):
            migration.restore_hourly_settings(apps, SimpleNamespace(connection=connection))
        restaurant.refresh_from_db()
        hall.refresh_from_db()
        self.assertEqual(restaurant.service_fee_mode, 'formula')
        self.assertEqual(hall.service_fee_formula, {'source': '50000'})

    def test_percentage_settings_are_unchanged_both_directions(self):
        restaurant = Restaurant.objects.create(name='Percentage', service_fee_enabled=True,
                                                service_fee_percent=15, service_fee_mode='percentage')
        before = Restaurant.objects.filter(pk=restaurant.pk).values().get()
        migration = import_module('apps.restaurants.migrations.0032_hourly_service_fees_to_formulas')
        migration.migrate_hourly_settings(apps, SimpleNamespace(connection=connection))
        migration.restore_hourly_settings(apps, SimpleNamespace(connection=connection))
        self.assertEqual(Restaurant.objects.filter(pk=restaurant.pk).values().get(), before)

    def test_reverse_refuses_to_orphan_formula_billing_history(self):
        migration = import_module('apps.restaurants.migrations.0032_hourly_service_fees_to_formulas')
        restaurant = Restaurant.objects.create(name='Historical formula', service_fee_enabled=True,
                                                service_fee_mode='hourly', service_fee_hourly_rate=100000)
        zone = ZoneOrCabin.objects.create(restaurant=restaurant, name='Zone')
        hall = Hall.objects.create(zone_or_cabin=zone, name='Hall')
        table = DiningTable.objects.create(hall=hall, name='Table', table_number='1')
        migration.migrate_hourly_settings(apps, SimpleNamespace(connection=connection))
        session = TableSession.objects.create(restaurant=restaurant, hall=hall, table=table,
                                             status='closed', closed_at=timezone.now())
        self.assertEqual(session.service_fee_snapshot[0]['mode'], 'formula')
        with self.assertRaisesRegex(RuntimeError, 'formula billing history'):
            migration.restore_hourly_settings(apps, SimpleNamespace(connection=connection))
        restaurant.refresh_from_db()
        self.assertEqual(restaurant.service_fee_mode, 'formula')
