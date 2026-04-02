import importlib
from unittest.mock import Mock

from django.test import SimpleTestCase


migration_module = importlib.import_module('apps.floor.migrations.0010_zone_catalog_and_hall_assignments')


class ZoneCatalogMigrationTests(SimpleTestCase):
    def test_existing_zone_assignments_are_backfilled(self):
        hall = Mock(id='hall-1', pk='hall-1', restaurant_id='restaurant-1')
        assigned_zone = Mock(id='zone-1', pk='zone-1', hall_id='hall-1', restaurant_id=None)
        assigned_zone.hall = hall
        hall.zone_or_cabin_id = None

        zone_update_queryset = Mock()
        hall_update_queryset = Mock()
        zone_manager = Mock()
        hall_manager = Mock()

        zone_manager.select_related.return_value.iterator.return_value = [assigned_zone]
        zone_manager.filter.return_value = zone_update_queryset
        hall_manager.iterator.return_value = [hall]
        hall_manager.filter.return_value = hall_update_queryset

        ZoneOrCabin = Mock(objects=zone_manager)
        Hall = Mock(objects=hall_manager)

        apps = Mock()
        apps.get_model.side_effect = lambda app_label, model_name: {
            ('floor', 'ZoneOrCabin'): ZoneOrCabin,
            ('floor', 'Hall'): Hall,
        }[(app_label, model_name)]

        migration_module.backfill_zone_catalog_and_hall_assignments(apps, schema_editor=None)

        self.assertEqual(zone_manager.select_related.call_count, 2)
        self.assertEqual(zone_manager.select_related.call_args_list[0].args, ('hall', 'hall__restaurant'))
        self.assertEqual(zone_manager.select_related.call_args_list[1].args, ('hall',))
        zone_manager.filter.assert_called_once_with(pk='zone-1')
        zone_update_queryset.update.assert_called_once_with(restaurant_id='restaurant-1')
        hall_manager.filter.assert_called_once_with(pk='hall-1')
        hall_update_queryset.update.assert_called_once_with(zone_or_cabin_id='zone-1')

    def test_migration_rejects_halls_without_exactly_one_zone(self):
        hall_without_zone = Mock(id='hall-1', pk='hall-1', restaurant_id='restaurant-1')
        zone_manager = Mock()
        hall_manager = Mock()

        zone_manager.select_related.return_value.iterator.return_value = []
        hall_manager.iterator.return_value = [hall_without_zone]

        ZoneOrCabin = Mock(objects=zone_manager)
        Hall = Mock(objects=hall_manager)

        apps = Mock()
        apps.get_model.side_effect = lambda app_label, model_name: {
            ('floor', 'ZoneOrCabin'): ZoneOrCabin,
            ('floor', 'Hall'): Hall,
        }[(app_label, model_name)]

        with self.assertRaisesMessage(RuntimeError, 'must have exactly one assigned zone or cabin'):
            migration_module.backfill_zone_catalog_and_hall_assignments(apps, schema_editor=None)
