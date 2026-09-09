from django.test import TestCase
from django.utils.translation import override

from apps.catalog.models import (
    CatalogCategory, CatalogItem, CatalogItemGroup, CatalogItemGroupMember,
    ModifierGroup, ModifierOption, CatalogItemModifierGroup,
)
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.local_agents.sync import _menu_snapshot
from apps.restaurants.models import Restaurant


class OfflineMenuTranslationsTests(TestCase):
    def test_snapshot_retains_translations_in_nested_menu(self):
        restaurant = Restaurant.objects.create(name="Translation fixture")
        category = CatalogCategory.objects.create(restaurant=restaurant, name_uz="Taom", name_ru="Food RU")
        item = CatalogItem.objects.create(restaurant=restaurant, category=category,
            name_uz="Choy", name_ru="Tea RU", description_ru="Description RU", price=1000)
        group = CatalogItemGroup.objects.create(restaurant=restaurant, category=category, name="Group")
        CatalogItemGroupMember.objects.create(group=group, catalog_item=item)
        modifier = ModifierGroup.objects.create(restaurant=restaurant, name_uz="Shakar", name_ru="Sugar RU")
        ModifierOption.objects.create(group=modifier, name_uz="Kam", name_ru="Less RU")
        CatalogItemModifierGroup.objects.create(catalog_item=item, modifier_group=modifier)
        with override("uz"):
            snapshot = _menu_snapshot(restaurant)[0]
            self.assertEqual(snapshot["name_ru"], "Food RU")
            product = snapshot["items"][0]
            self.assertEqual(product["name_ru"], "Tea RU")
            self.assertEqual(product["description_ru"], "Description RU")
            self.assertEqual(product["modifier_groups"][0]["name_ru"], "Sugar RU")
            self.assertEqual(product["modifier_groups"][0]["options"][0]["name_ru"], "Less RU")
            self.assertEqual(snapshot["item_groups"][0]["members"][0]["item"]["name_ru"], "Tea RU")
        with override("ru"):
            online = CatalogMenuCategorySerializer(category).data
            self.assertEqual(online["name"], "Food RU")
            self.assertNotIn("name_ru", online)
