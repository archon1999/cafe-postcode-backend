from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase, SimpleTestCase
from django.utils.translation import override

from apps.restaurants.models import Restaurant
from apps.restaurants.selectors.restaurants import RestaurantListFilters


class RestaurantSingleNameTests(TestCase):
    def test_name_is_shared_across_languages_and_search(self):
        with override('ru'):
            restaurant = Restaurant.objects.create(name='OLMOS QASSOB', legal_name='OLMOS MCHJ')
        for language in ('uz', 'uz-crl', 'ru'):
            with override(language):
                saved = Restaurant.objects.get(pk=restaurant.pk)
                self.assertEqual(saved.name, 'OLMOS QASSOB')
                self.assertEqual(saved.legal_name, 'OLMOS MCHJ')
                self.assertTrue(RestaurantListFilters(search='OLMOS').apply(Restaurant.objects.all()).filter(pk=saved.pk).exists())
        with override('uz'):
            restaurant.name = 'OLMOS CAFE'
            restaurant.save(update_fields=['name'])
        with override('ru'):
            self.assertEqual(Restaurant.objects.get(pk=restaurant.pk).name, 'OLMOS CAFE')


class RestaurantNameMigrationTests(SimpleTestCase):
    def test_preserves_original_and_recovers_translation_only_names(self):
        migrate = import_module('apps.restaurants.migrations.0029_restaurant_single_name').preserve_names
        model = Mock()
        queryset = model.objects.using.return_value
        queryset.all.return_value.iterator.return_value = [
            SimpleNamespace(pk=1, name='Original', legal_name='Legal'),
            SimpleNamespace(pk=2, name='', name_uz=None, name_ru='Russian only', legal_name='', legal_name_uz=None, legal_name_ru='Legal only'),
        ]
        apps = Mock()
        apps.get_model.return_value = model
        migrate(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        queryset.filter.assert_called_once_with(pk=2)
        queryset.filter.return_value.update.assert_called_once_with(name='Russian only', legal_name='Legal only')
