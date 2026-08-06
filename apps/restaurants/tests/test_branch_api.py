from decimal import Decimal

from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.catalog.models import (
    CatalogCategory,
    CatalogItem,
    CatalogItemModifierGroup,
    ModifierGroup,
    ModifierOption,
)
from apps.restaurants.models import PrepStation, Restaurant
from apps.users.models import User


class RestaurantBranchApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='branch-admin',
            password='secret123',
            full_name='Branch Admin',
        )
        cls.parent = Restaurant.objects.create(
            name='Parent restaurant',
            service_fee_enabled=True,
            service_fee_percent=Decimal('10.00'),
            vat_enabled=True,
            vat_percent=Decimal('12.00'),
            marking_check_enabled=True,
            pos_monitor_variant=Restaurant.PosMonitorVariant.LIGHT_COMPACT,
        )
        cls.station = PrepStation.objects.create(
            restaurant=cls.parent,
            name='Kitchen',
            kind=PrepStation.Kind.KITCHEN,
        )
        cls.category = CatalogCategory.objects.create(
            restaurant=cls.parent,
            prep_station=cls.station,
            name='Meals',
        )
        cls.modifier_group = ModifierGroup.objects.create(
            restaurant=cls.parent,
            name='Sauce',
            selection_type=ModifierGroup.SelectionType.SINGLE,
        )
        ModifierOption.objects.create(
            group=cls.modifier_group,
            name='Cheese sauce',
            price_delta=3000,
        )
        cls.item = CatalogItem.objects.create(
            restaurant=cls.parent,
            category=cls.category,
            prep_station=cls.station,
            name='Burger',
            price=35000,
            is_stoplisted=True,
        )
        CatalogItemModifierGroup.objects.create(
            catalog_item=cls.item,
            modifier_group=cls.modifier_group,
            sort_order=2,
        )

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_create_branch_copies_safe_settings_and_catalog_graph(self):
        response = self.client.post(
            f'/api/v1/admin/restaurants/{self.parent.id}/branches/',
            {
                'name': 'Chilonzor branch',
                'address': 'Chilonzor',
                'copy_catalog': True,
                'copy_settings': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        branch = Restaurant.objects.get(pk=response.data['id'])
        self.assertEqual(branch.parent_restaurant, self.parent)
        self.assertEqual(branch.service_fee_percent, self.parent.service_fee_percent)
        self.assertTrue(branch.marking_check_enabled)

        station = branch.prep_stations.get(name='Kitchen')
        category = branch.catalog_categories.get(name='Meals')
        item = branch.catalog_items.get(name='Burger')
        modifier_group = branch.modifier_groups.get(name='Sauce')

        self.assertEqual(category.prep_station, station)
        self.assertEqual(item.prep_station, station)
        self.assertEqual(item.category, category)
        self.assertFalse(item.is_stoplisted)
        self.assertEqual(modifier_group.options.get().name, 'Cheese sauce')
        self.assertTrue(
            CatalogItemModifierGroup.objects.filter(
                catalog_item=item,
                modifier_group=modifier_group,
                sort_order=2,
            ).exists()
        )
        self.assertTrue(branch.print_templates.exists())

    def test_create_branch_without_copy_flags_keeps_catalog_empty(self):
        response = self.client.post(
            f'/api/v1/admin/restaurants/{self.parent.id}/branches/',
            {'name': 'Empty branch'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        branch = Restaurant.objects.get(pk=response.data['id'])
        self.assertFalse(branch.catalog_items.exists())
        self.assertFalse(branch.prep_stations.exists())
        self.assertFalse(branch.service_fee_enabled)

    def test_branch_cannot_create_nested_branch_and_protects_parent(self):
        child = Restaurant.objects.create(
            name='Existing branch',
            parent_restaurant=self.parent,
        )

        response = self.client.post(
            f'/api/v1/admin/restaurants/{child.id}/branches/',
            {'name': 'Nested branch'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        with self.assertRaises(ProtectedError):
            self.parent.delete()
