from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.catalog.models import CatalogItem, ModifierGroup, ModifierOption
from apps.inventory.management.commands.seed_qamish_inventory import (
    QAMISH_RESTAURANT_ID,
    QAMISH_RESTAURANT_NAME,
)
from apps.inventory.models import InventoryItem, Recipe, StockBalance, StockDocument, Warehouse
from apps.inventory.services import default_warehouse
from apps.restaurants.models import Restaurant


class SeedQamishInventoryTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(id=QAMISH_RESTAURANT_ID, name=QAMISH_RESTAURANT_NAME)
        self.other = Restaurant.objects.create(name='Boshqa restoran')
        old_store = default_warehouse(self.restaurant)
        InventoryItem.objects.create(restaurant=self.restaurant, name='Eski mahsulot', base_unit='g')
        other_store = default_warehouse(self.other)
        self.other_item = InventoryItem.objects.create(restaurant=self.other, name='Saqlanadigan mahsulot', base_unit='g')
        StockBalance.objects.create(warehouse=other_store, item=self.other_item, quantity=25)

        products = {
            name: CatalogItem.objects.create(restaurant=self.restaurant, name=name, price=price)
            for name, price in (
                ('CHICKEN BURGER', 43000),
                ('QAMISH KLASSIK BURGER', 49000),
                ('KARTOSHKA FRI', 22000),
                ('KAPUCHINO', 28000),
                ('COCA-COLA 0.5 L', 16000),
            )
        }
        extras = ModifierGroup.objects.create(
            restaurant=self.restaurant,
            name='Qo‘shimchalar',
            selection_type='multiple',
            max_selections=6,
        )
        removals = ModifierGroup.objects.create(
            restaurant=self.restaurant,
            name='Olib tashlash',
            selection_type='multiple',
            max_selections=5,
        )
        for index, name in enumerate(
            ('Qo‘shimcha pishloq', 'Bekon', 'Qo‘ziqorin', 'Jalapeno', 'Qo‘shimcha kotlet', 'Tuxum')
        ):
            ModifierOption.objects.create(group=extras, name=name, sort_order=index)
        for index, name in enumerate(('Piyozsiz', 'Pomidorsiz', 'Bodringsiz', 'Ko‘katsiz', 'Soussiz')):
            ModifierOption.objects.create(group=removals, name=name, sort_order=index)
        for product in (products['CHICKEN BURGER'], products['QAMISH KLASSIK BURGER']):
            product.modifier_groups.add(extras, removals)
        self.assertTrue(Warehouse.objects.filter(pk=old_store.pk).exists())

    def test_seed_replaces_only_qamish_inventory_with_complete_operational_flow(self):
        output = StringIO()
        call_command(
            'seed_qamish_inventory',
            restaurant_id=QAMISH_RESTAURANT_ID,
            confirm_name=QAMISH_RESTAURANT_NAME,
            reference_date='2026-09-16',
            apply=True,
            stdout=output,
        )

        self.assertEqual(Warehouse.objects.filter(restaurant=self.restaurant).count(), 3)
        self.assertEqual(InventoryItem.objects.filter(restaurant=self.restaurant).count(), 26)
        self.assertEqual(Recipe.objects.filter(restaurant=self.restaurant).count(), 8)
        self.assertEqual(StockDocument.objects.filter(restaurant=self.restaurant, status='posted').count(), 28)
        self.assertEqual(
            set(StockDocument.objects.filter(restaurant=self.restaurant).values_list('kind', flat=True)),
            {'receipt', 'transfer', 'production', 'sale', 'issue', 'stocktake'},
        )
        sales_store = Warehouse.objects.get(restaurant=self.restaurant, is_default=True)
        cola = InventoryItem.objects.get(restaurant=self.restaurant, name='Coca-Cola 0.5 L')
        self.assertEqual(StockBalance.objects.get(warehouse=sales_store, item=cola).quantity, 0)
        self.assertEqual(InventoryItem.objects.filter(restaurant=self.other).count(), 1)
        self.assertEqual(StockBalance.objects.get(item=self.other_item).quantity, 25)
        self.assertEqual(CatalogItem.objects.filter(restaurant=self.restaurant).count(), 5)
        self.assertIn('Qamish ombori muvaffaqiyatli qayta yaratildi.', output.getvalue())

    def test_seed_requires_exact_restaurant_identity_and_apply_flag(self):
        with self.assertRaises(CommandError):
            call_command(
                'seed_qamish_inventory',
                restaurant_id=QAMISH_RESTAURANT_ID,
                confirm_name=QAMISH_RESTAURANT_NAME,
            )
        with self.assertRaises(CommandError):
            call_command(
                'seed_qamish_inventory',
                restaurant_id=str(self.other.pk),
                confirm_name=self.other.name,
                apply=True,
            )
        self.assertTrue(InventoryItem.objects.filter(restaurant=self.restaurant, name='Eski mahsulot').exists())
