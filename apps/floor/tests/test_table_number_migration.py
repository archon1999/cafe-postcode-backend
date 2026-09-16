from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class TableNumberMigrationTests(TransactionTestCase):
    def test_existing_numbers_become_strings_without_changing_table_identity(self):
        previous = [('floor', '0007_hourly_service_fees')]
        target = [('floor', '0008_diningtable_string_number')]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            restaurant = apps.get_model('restaurants', 'Restaurant').objects.create(name='Migration test')
            zone = apps.get_model('floor', 'ZoneOrCabin').objects.create(restaurant=restaurant, name='Zone')
            hall = apps.get_model('floor', 'Hall').objects.create(zone_or_cabin=zone, name='Hall')
            table = apps.get_model('floor', 'DiningTable').objects.create(
                hall=hall, name='Original name', table_number=12, position_x=3, position_y=2,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            migrated = apps.get_model('floor', 'DiningTable').objects.get(pk=table.pk)
            self.assertEqual(migrated.table_number, '12')
            self.assertEqual(migrated.name, 'Original name')
            self.assertEqual(migrated.position_x, 3)
            self.assertEqual(migrated.position_y, 2)
            migrated.table_number = 'VIP-02'
            migrated.save(update_fields=('table_number',))
            migrated.refresh_from_db()
            self.assertEqual(migrated.table_number, 'VIP-02')
        finally:
            MigrationExecutor(connection).migrate(target)
