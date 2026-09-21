"""Real migration graph rehearsal; run on the isolated PostgreSQL test database."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ServiceFeeMigrationRehearsalTests(TransactionTestCase):
    def test_forward_reverse_forward_preserves_fees_snapshots_and_receipts(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        before = [('restaurants', '0029_restaurant_single_name'),
                  ('floor', '0008_diningtable_string_number'),
                  ('printing', '0014_publish_item_line_totals')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old = executor.loader.project_state(before).apps
            Restaurant = old.get_model('restaurants', 'Restaurant')
            Zone = old.get_model('floor', 'ZoneOrCabin')
            Hall = old.get_model('floor', 'Hall')
            Table = old.get_model('floor', 'DiningTable')
            Session = old.get_model('floor', 'TableSession')
            Template = old.get_model('printing', 'PrintTemplate')
            Version = old.get_model('printing', 'PrintTemplateVersion')
            percentage = Restaurant.objects.create(name='Percentage', service_fee_enabled=True,
                                                    service_fee_mode='percentage', service_fee_percent=15)
            restaurant = Restaurant.objects.create(name='Lumen rehearsal')
            zone = Zone.objects.create(restaurant=restaurant, name='Zone')
            hall = Hall.objects.create(zone_or_cabin=zone, name='Kabina', service_fee_enabled=True,
                                       service_fee_mode='hourly', service_fee_hourly_rate=100000)
            table = Table.objects.create(hall=hall, name='Table', table_number='1')
            snapshot = [{'scope': 'hall', 'mode': 'hourly', 'hourly_rate': 100000}]
            session = Session.objects.create(restaurant=restaurant, hall=hall, table=table,
                                             service_fee_snapshot=snapshot)
            template = Template.objects.create(restaurant=percentage, kind='order_precheck')
            layout = {'blocks': [{'type': 'totals', 'rows': [
                {'label': 'Restoran ({{totals.restaurantServiceFeeRateLabel}})',
                 'value': '{{totals.restaurantServiceFee}}'},
            ]}]}
            version = Version.objects.create(template=template, revision=1, status='published', layout=layout)
            template.published_version = version
            template.save()

            for attempt in range(2):
                executor = MigrationExecutor(connection)
                executor.migrate(latest)
                current = executor.loader.project_state(latest).apps
                migrated = current.get_model('floor', 'Hall').objects.get(pk=hall.pk)
                self.assertEqual(migrated.service_fee_mode, 'formula')
                self.assertEqual(migrated.service_fee_formula['parameters'], {'hourly_rate': '100000'})
                self.assertEqual(current.get_model('restaurants', 'Restaurant').objects.get(
                    pk=percentage.pk).service_fee_percent, 15)
                self.assertEqual(current.get_model('floor', 'TableSession').objects.get(
                    pk=session.pk).service_fee_snapshot, snapshot)
                new_template = current.get_model('printing', 'PrintTemplate').objects.select_related(
                    'published_version').get(pk=template.pk)
                self.assertEqual(new_template.published_version.layout['blocks'][0]['rows'][0]['label'],
                                 '{{totals.restaurantServiceFeeLabel}}')
                if attempt == 0:
                    executor = MigrationExecutor(connection)
                    executor.migrate(before)
                    restored = executor.loader.project_state(before).apps
                    restored_hall = restored.get_model('floor', 'Hall').objects.get(pk=hall.pk)
                    self.assertEqual(restored_hall.service_fee_mode, 'hourly')
                    self.assertEqual(restored_hall.service_fee_hourly_rate, 100000)
                    self.assertEqual(restored.get_model('printing', 'PrintTemplate').objects.get(
                        pk=template.pk).published_version_id, version.pk)
                    self.assertEqual(restored.get_model('printing', 'PrintTemplateVersion').objects.get(
                        pk=version.pk).layout, layout)
        finally:
            MigrationExecutor(connection).migrate(latest)
