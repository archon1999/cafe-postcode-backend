from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import CatalogItem, ModifierOption
from apps.restaurants.models import Restaurant
from apps.inventory.models import (
    ConsumptionResolution,
    InventoryAttachment,
    InventoryItem,
    OrderConsumption,
    Recipe,
    RecipeLine,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockMovement,
    Supplier,
    Warehouse,
)
from apps.inventory.services import (
    components_for,
    create_document,
    create_recipe,
    finish_document,
    locked_balance,
    make_document,
    post_document,
    record_movement,
)


QAMISH_RESTAURANT_ID = 'bf4e5bb4-fc17-486a-b332-f67fc75af5f0'
QAMISH_RESTAURANT_NAME = '"Qamish Gamburg"'
TASHKENT = ZoneInfo('Asia/Tashkent')


class Command(BaseCommand):
    help = (
        'Qamish omborini tozalab, real restoran oqimini ko‘rsatuvchi kirim, transfer, '
        'ishlab chiqarish, retsept sarfi, chiqim va inventarizatsiya ma’lumotlari bilan to‘ldiradi.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--restaurant-id', required=True)
        parser.add_argument('--confirm-name', required=True)
        parser.add_argument('--reference-date', default=timezone.localdate().isoformat())
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not options['apply']:
            raise CommandError('Ma’lumot yozish uchun --apply majburiy.')
        if options['restaurant_id'] != QAMISH_RESTAURANT_ID:
            raise CommandError('Bu command faqat Qamish restoranining tasdiqlangan UUID qiymatini qabul qiladi.')
        if options['confirm_name'] != QAMISH_RESTAURANT_NAME:
            raise CommandError('Restoran nomi aniq mos kelmadi; amal bekor qilindi.')
        try:
            reference_date = date.fromisoformat(options['reference_date'])
        except ValueError as error:
            raise CommandError('--reference-date YYYY-MM-DD formatida bo‘lishi kerak.') from error
        if reference_date > timezone.localdate() + timedelta(days=1):
            raise CommandError('Kelajakdagi tayanch sana qabul qilinmaydi.')

        with transaction.atomic():
            restaurant = Restaurant.objects.select_for_update().get(pk=QAMISH_RESTAURANT_ID)
            if restaurant.name != QAMISH_RESTAURANT_NAME:
                raise CommandError('Bazadagi restoran nomi kutilgan qiymatga mos emas.')
            before = self._counts(restaurant)
            self._clear_inventory(restaurant)
            summary = self._seed(restaurant, reference_date)
            after = self._counts(restaurant)

        payload = {
            'restaurantId': str(restaurant.pk),
            'restaurantName': restaurant.name,
            'referenceDate': reference_date.isoformat(),
            'before': before,
            'after': after,
            **summary,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))
        self.stdout.write(self.style.SUCCESS('Qamish ombori muvaffaqiyatli qayta yaratildi.'))

    @staticmethod
    def _counts(restaurant):
        return {
            'warehouses': Warehouse.objects.filter(restaurant=restaurant).count(),
            'items': InventoryItem.objects.filter(restaurant=restaurant).count(),
            'suppliers': Supplier.objects.filter(restaurant=restaurant).count(),
            'documents': StockDocument.objects.filter(restaurant=restaurant).count(),
            'movements': StockMovement.objects.filter(document__restaurant=restaurant).count(),
            'recipes': Recipe.objects.filter(restaurant=restaurant).count(),
            'attachments': InventoryAttachment.objects.filter(restaurant=restaurant).count(),
        }

    @staticmethod
    def _clear_inventory(restaurant):
        documents = StockDocument.objects.filter(restaurant=restaurant)
        OrderConsumption.objects.filter(restaurant=restaurant).update(source_consumption=None)
        ConsumptionResolution.objects.filter(consumption__restaurant=restaurant).delete()
        OrderConsumption.objects.filter(restaurant=restaurant).delete()
        StockMovement.objects.filter(document__restaurant=restaurant).delete()
        StockDocumentLine.objects.filter(document__restaurant=restaurant).delete()
        documents.update(reversal_of=None)
        documents.delete()
        RecipeLine.objects.filter(recipe__restaurant=restaurant).delete()
        Recipe.objects.filter(restaurant=restaurant).delete()
        StockBalance.objects.filter(warehouse__restaurant=restaurant).delete()
        InventoryAttachment.objects.filter(restaurant=restaurant).delete()
        InventoryItem.objects.filter(restaurant=restaurant).delete()
        Supplier.objects.filter(restaurant=restaurant).delete()
        Warehouse.objects.filter(restaurant=restaurant).delete()

    def _seed(self, restaurant, reference_date):
        occurred = lambda offset, hour=10: datetime.combine(
            reference_date + timedelta(days=offset), time(hour=hour), tzinfo=TASHKENT
        )

        raw_store = Warehouse.objects.create(
            restaurant=restaurant,
            name='Xomashyo ombori',
            kind=Warehouse.Kind.RAW,
        )
        production_store = Warehouse.objects.create(
            restaurant=restaurant,
            name='Ishlab chiqarish ombori',
            kind=Warehouse.Kind.PRODUCTION,
        )
        sales_store = Warehouse.objects.create(
            restaurant=restaurant,
            name='Sotuv ombori',
            kind=Warehouse.Kind.SALES,
            is_default=True,
        )

        suppliers = {
            'meat': Supplier.objects.create(
                restaurant=restaurant,
                name='Toshkent Parranda va Go‘sht Ta’minoti',
                tax_number='309884512',
                phone='+998 71 200 18 18',
                address='Toshkent shahri, Bektemir tumani',
            ),
            'produce': Supplier.objects.create(
                restaurant=restaurant,
                name='Baraka Sabzavot Servis',
                tax_number='307552901',
                phone='+998 90 944 22 11',
                address='Toshkent shahri, Qo‘yliq ulgurji bozori',
            ),
            'bakery': Supplier.objects.create(
                restaurant=restaurant,
                name='Oqtepa Non va Sut Mahsulotlari',
                tax_number='308117640',
                phone='+998 71 248 40 40',
                address='Toshkent shahri, Chilonzor tumani',
            ),
            'grocery': Supplier.objects.create(
                restaurant=restaurant,
                name='Premium Food Distribution',
                tax_number='306441278',
                phone='+998 78 120 70 70',
                address='Toshkent shahri, Sergeli tumani',
            ),
        }

        def item(key, name, base_unit, purchase_unit, factor, minimum, *, kind='raw', mode='warn',
                 tolerance_percent='5', tolerance_quantity='0', tolerance_value='0'):
            value = InventoryItem.objects.create(
                restaurant=restaurant,
                name=name,
                kind=kind,
                sku=f'QM-{key.upper().replace("_", "-")}',
                base_unit=base_unit,
                purchase_unit=purchase_unit,
                purchase_factor=Decimal(factor),
                min_quantity=Decimal(minimum),
                tolerance_percent=Decimal(tolerance_percent),
                tolerance_quantity=Decimal(tolerance_quantity),
                tolerance_value=Decimal(tolerance_value),
                availability_mode=mode,
            )
            items[key] = value
            return value

        items = {}
        item('chicken', 'Tovuq filesi', 'g', 'kg', '1000', '15000', tolerance_quantity='1500')
        item('beef', 'Mol go‘shti', 'g', 'kg', '1000', '10000', tolerance_quantity='1000')
        item('potato', 'Kartoshka', 'g', 'kg', '1000', '30000', tolerance_quantity='2500')
        item('onion', 'Piyoz', 'g', 'kg', '1000', '8000', tolerance_quantity='700')
        item('tomato', 'Pomidor', 'g', 'kg', '1000', '8000', tolerance_quantity='700')
        item('pickles', 'Tuzlangan bodring', 'g', 'kg', '1000', '4000', tolerance_quantity='400')
        item('greens', 'Ko‘kat', 'g', 'kg', '1000', '1500', tolerance_quantity='250')
        item('sauce', 'Burger sousi', 'ml', 'litr', '1000', '5000', tolerance_quantity='1000')
        item('cheese', 'Pishloq bo‘lagi', 'piece', 'dona', '1', '40', tolerance_quantity='5')
        item('bacon', 'Bekon', 'g', 'kg', '1000', '2500', tolerance_quantity='500')
        item('mushroom', 'Qo‘ziqorin', 'g', 'kg', '1000', '2500', tolerance_quantity='400')
        item('jalapeno', 'Jalapeno', 'g', 'kg', '1000', '1000', tolerance_quantity='200')
        item('egg', 'Tuxum', 'piece', 'dona', '1', '60', tolerance_quantity='5')
        item('bun', 'Burger bulochkasi', 'piece', 'dona', '1', '80', mode='block', tolerance_quantity='5')
        item('oil', 'Qovurish yog‘i', 'ml', 'litr', '1000', '8000', tolerance_quantity='1000')
        item('salt', 'Osh tuzi', 'g', 'kg', '1000', '2000', tolerance_quantity='300')
        item('coffee', 'Qahva doni', 'g', 'kg', '1000', '3000', mode='block', tolerance_quantity='300')
        item('milk', 'Sut 3.2%', 'ml', 'litr', '1000', '20000', mode='block', tolerance_quantity='1000')
        item('sugar', 'Shakar', 'g', 'kg', '1000', '5000', tolerance_quantity='500')
        item('cola', 'Coca-Cola 0.5 L', 'piece', 'dona', '1', '20', kind='finished', mode='block')
        item('burger_box', 'Burger qutisi', 'piece', 'dona', '1', '80', kind='packaging')
        item('fries_box', 'Fri qutisi', 'piece', 'dona', '1', '80', kind='packaging')
        item('cup', '300 ml qog‘oz stakan va qopqoq', 'piece', 'dona', '1', '60', kind='packaging')
        item('chicken_patty', 'Chicken Patty', 'piece', 'dona', '1', '40', kind='semi_finished', mode='block', tolerance_percent='3')
        item('beef_patty', 'Mol go‘shti kotleti', 'piece', 'dona', '1', '30', kind='semi_finished', mode='block', tolerance_percent='3')
        item('fries_prep', 'Tozalangan fri kartoshkasi', 'g', 'kg', '1000', '10000', kind='semi_finished', mode='block', tolerance_percent='4')

        def post(kind, warehouse, reference, at, lines, *, supplier=None, destination=None,
                 recipe=None, planned=None, actual=None, reason='', notes=''):
            data = {
                'kind': kind,
                'warehouse': str(warehouse.pk),
                'reference': reference,
                'occurred_at': at,
                'responsible_name': 'Qamish ombor mudiri',
                'reason': reason,
                'notes': notes,
                'idempotency_key': f'qamish-seed:{reference}',
                'lines': lines,
            }
            if supplier:
                data['supplier'] = str(supplier.pk)
            if destination:
                data['destination_warehouse'] = str(destination.pk)
            if recipe:
                data.update({
                    'production_recipe': str(recipe.pk),
                    'planned_quantity': str(planned),
                    'actual_quantity': str(actual),
                })
            document = create_document(restaurant, data)
            return post_document(document)

        def purchase_line(key, quantity, unit_cost, discount='0', *, lot='', expires=None):
            return {
                'item': str(items[key].pk),
                'quantity': str(quantity),
                'input_unit': 'purchase',
                'unit_cost': str(unit_cost),
                'discount_percent': str(discount),
                'lot_number': lot,
                'expires_on': expires,
            }

        post('receipt', raw_store, 'TPG-2608-0417', occurred(-28), [
            purchase_line('chicken', 120, 48000, 5, lot='TF-0826-17', expires=reference_date + timedelta(days=12)),
            purchase_line('beef', 90, 78000, 3, lot='MG-0826-09', expires=reference_date + timedelta(days=18)),
            purchase_line('bacon', 18, 92000, 4, lot='BK-0826-04', expires=reference_date + timedelta(days=20)),
            purchase_line('egg', 300, 1400, 2, lot='TX-0826-21', expires=reference_date + timedelta(days=10)),
        ], supplier=suppliers['meat'])
        post('receipt', raw_store, 'BSS-2608-1182', occurred(-27), [
            purchase_line('potato', 160, 6000, 10, lot='KR-0826-44', expires=reference_date + timedelta(days=25)),
            purchase_line('onion', 40, 5200, 5, lot='PY-0826-12', expires=reference_date + timedelta(days=20)),
            purchase_line('tomato', 55, 14500, 5, lot='PM-0826-18', expires=reference_date + timedelta(days=7)),
            purchase_line('pickles', 25, 26000, 3, lot='TB-0826-06', expires=reference_date + timedelta(days=45)),
            purchase_line('greens', 8, 36000, 4, lot='KK-0826-31', expires=reference_date + timedelta(days=4)),
            purchase_line('mushroom', 20, 42000, 5, lot='QZ-0826-14', expires=reference_date + timedelta(days=8)),
            purchase_line('jalapeno', 8, 68000, 5, lot='JL-0826-03', expires=reference_date + timedelta(days=35)),
        ], supplier=suppliers['produce'])
        post('receipt', raw_store, 'ONS-2608-337', occurred(-26), [
            purchase_line('bun', 500, 2600, 8, lot='BN-0826-08', expires=reference_date + timedelta(days=5)),
            purchase_line('cheese', 350, 3100, 7, lot='PS-0826-11', expires=reference_date + timedelta(days=30)),
            purchase_line('milk', 160, 8500, 5, lot='ST-0826-27', expires=reference_date + timedelta(days=6)),
        ], supplier=suppliers['bakery'])
        post('receipt', raw_store, 'PFD-2608-9015', occurred(-25), [
            purchase_line('sauce', 30, 28000, 6, lot='BS-0826-07', expires=reference_date + timedelta(days=21)),
            purchase_line('oil', 50, 21000, 5, lot='QY-0826-19', expires=reference_date + timedelta(days=120)),
            purchase_line('salt', 20, 4800, 0, lot='OT-0826-02', expires=reference_date + timedelta(days=300)),
            purchase_line('coffee', 20, 148000, 5, lot='QD-0826-05', expires=reference_date + timedelta(days=90)),
            purchase_line('sugar', 40, 9200, 5, lot='SH-0826-16', expires=reference_date + timedelta(days=180)),
            purchase_line('cola', 400, 7800, 4, lot='CC-0826-51', expires=reference_date + timedelta(days=150)),
            purchase_line('burger_box', 500, 1150, 5, lot='BQ-0826-08'),
            purchase_line('fries_box', 500, 850, 5, lot='FQ-0826-08'),
            purchase_line('cup', 300, 1350, 5, lot='QS-0826-08'),
        ], supplier=suppliers['grocery'])

        post('receipt', raw_store, 'TPG-2609-0528', occurred(-7), [
            purchase_line('chicken', 30, 55000, 4, lot='TF-0926-28', expires=reference_date + timedelta(days=14)),
        ], supplier=suppliers['meat'])
        post('receipt', raw_store, 'BSS-2609-1340', occurred(-6), [
            purchase_line('potato', 50, 6600, 5, lot='KR-0926-40', expires=reference_date + timedelta(days=28)),
        ], supplier=suppliers['produce'])
        post('receipt', raw_store, 'ONS-2609-411', occurred(-5), [
            purchase_line('milk', 40, 10200, 5, lot='ST-0926-41', expires=reference_date + timedelta(days=2)),
        ], supplier=suppliers['bakery'])

        def base_line(key, quantity):
            return {'item': str(items[key].pk), 'quantity': str(quantity), 'input_unit': 'base'}

        post('transfer', raw_store, 'TR-RAW-PROD-2609-01', occurred(-24), [
            base_line('chicken', 60000), base_line('beef', 50000), base_line('potato', 120000),
            base_line('onion', 15000), base_line('oil', 5000), base_line('salt', 5000),
        ], destination=production_store)

        chicken_prep = create_recipe(restaurant, {
            'output_item': str(items['chicken_patty'].pk),
            'name': 'Chicken Patty texnologik kartasi',
            'yield_quantity': '100',
            'lines': [
                base_line('chicken', 18000), base_line('onion', 2000),
                base_line('oil', 500), base_line('salt', 300),
            ],
        })
        beef_prep = create_recipe(restaurant, {
            'output_item': str(items['beef_patty'].pk),
            'name': 'Mol go‘shti kotleti texnologik kartasi',
            'yield_quantity': '100',
            'lines': [
                base_line('beef', 20000), base_line('onion', 3000),
                base_line('oil', 500), base_line('salt', 400),
            ],
        })
        fries_prep = create_recipe(restaurant, {
            'output_item': str(items['fries_prep'].pk),
            'name': 'Fri kartoshkasini tayyorlash kartasi',
            'yield_quantity': '85000',
            'lines': [base_line('potato', 100000)],
        })
        post('production', production_store, 'PRD-2609-CH-01', occurred(-23), [],
             recipe=chicken_prep, planned=300, actual=288,
             notes='Rejadagi chiqishga nisbatan 4% texnologik yo‘qotish qayd etildi.')
        post('production', production_store, 'PRD-2609-BF-01', occurred(-22), [],
             recipe=beef_prep, planned=220, actual=208,
             notes='Partiya chiqishi tortish natijasi bo‘yicha kiritildi.')
        post('production', production_store, 'PRD-2609-FR-01', occurred(-21), [],
             recipe=fries_prep, planned=85000, actual=80000,
             notes='Saralash va tozalashdan keyingi haqiqiy chiqish.')

        post('transfer', production_store, 'TR-PROD-SALES-2609-01', occurred(-20), [
            base_line('chicken_patty', 240), base_line('beef_patty', 180), base_line('fries_prep', 70000),
        ], destination=sales_store)
        post('transfer', raw_store, 'TR-RAW-SALES-2609-02', occurred(-20, 12), [
            base_line('bun', 450), base_line('sauce', 25000), base_line('onion', 15000),
            base_line('tomato', 40000), base_line('pickles', 20000), base_line('greens', 6000),
            base_line('cheese', 300), base_line('bacon', 15000), base_line('mushroom', 15000),
            base_line('jalapeno', 6000), base_line('egg', 250), base_line('oil', 30000),
            base_line('salt', 10000), base_line('coffee', 15000), base_line('milk', 120000),
            base_line('sugar', 30000), base_line('cola', 120), base_line('burger_box', 300),
            base_line('fries_box', 300), base_line('cup', 250),
        ], destination=sales_store)

        catalog = {
            name: CatalogItem.objects.get(restaurant=restaurant, name=name, is_active=True, item_type='product')
            for name in ('CHICKEN BURGER', 'QAMISH KLASSIK BURGER', 'KARTOSHKA FRI', 'KAPUCHINO', 'COCA-COLA 0.5 L')
        }
        modifiers = {
            option.name: option
            for option in ModifierOption.objects.filter(
                group__restaurant=restaurant,
                group__name__in=('Qo‘shimchalar', 'Olib tashlash'),
                is_active=True,
            ).select_related('group')
        }

        def modifier_line(key, quantity, option_name, condition='selected'):
            return {
                **base_line(key, quantity),
                'modifier_option': str(modifiers[option_name].pk),
                'modifier_condition': condition,
            }

        chicken_recipe = create_recipe(restaurant, {
            'catalog_item': str(catalog['CHICKEN BURGER'].pk),
            'name': 'CHICKEN BURGER standart retsepti',
            'yield_quantity': '1',
            'trigger': 'dispatch',
            'lines': [
                base_line('chicken_patty', 1), base_line('bun', 1), base_line('burger_box', 1),
                modifier_line('sauce', 25, 'Soussiz', 'not_selected'),
                modifier_line('onion', 15, 'Piyozsiz', 'not_selected'),
                modifier_line('tomato', 30, 'Pomidorsiz', 'not_selected'),
                modifier_line('pickles', 20, 'Bodringsiz', 'not_selected'),
                modifier_line('greens', 5, 'Ko‘katsiz', 'not_selected'),
                modifier_line('cheese', 1, 'Qo‘shimcha pishloq'),
                modifier_line('bacon', 40, 'Bekon'),
                modifier_line('mushroom', 30, 'Qo‘ziqorin'),
                modifier_line('jalapeno', 15, 'Jalapeno'),
                modifier_line('chicken_patty', 1, 'Qo‘shimcha kotlet'),
                modifier_line('egg', 1, 'Tuxum'),
            ],
        })
        classic_recipe = create_recipe(restaurant, {
            'catalog_item': str(catalog['QAMISH KLASSIK BURGER'].pk),
            'name': 'QAMISH KLASSIK BURGER standart retsepti',
            'yield_quantity': '1',
            'trigger': 'dispatch',
            'lines': [
                base_line('beef_patty', 1), base_line('bun', 1), base_line('burger_box', 1),
                modifier_line('sauce', 25, 'Soussiz', 'not_selected'),
                modifier_line('onion', 18, 'Piyozsiz', 'not_selected'),
                modifier_line('tomato', 35, 'Pomidorsiz', 'not_selected'),
                modifier_line('pickles', 20, 'Bodringsiz', 'not_selected'),
                modifier_line('greens', 5, 'Ko‘katsiz', 'not_selected'),
                modifier_line('cheese', 1, 'Qo‘shimcha pishloq'),
                modifier_line('bacon', 40, 'Bekon'),
                modifier_line('mushroom', 30, 'Qo‘ziqorin'),
                modifier_line('jalapeno', 15, 'Jalapeno'),
                modifier_line('egg', 1, 'Tuxum'),
            ],
        })
        fries_recipe = create_recipe(restaurant, {
            'catalog_item': str(catalog['KARTOSHKA FRI'].pk),
            'name': 'KARTOSHKA FRI standart retsepti',
            'yield_quantity': '1',
            'trigger': 'dispatch',
            'lines': [base_line('fries_prep', 180), base_line('oil', 15), base_line('salt', 2), base_line('fries_box', 1)],
        })
        cappuccino_recipe = create_recipe(restaurant, {
            'catalog_item': str(catalog['KAPUCHINO'].pk),
            'name': 'KAPUCHINO 300 ml standart retsepti',
            'yield_quantity': '1',
            'trigger': 'dispatch',
            'lines': [base_line('coffee', 18), base_line('milk', 180), base_line('sugar', 8), base_line('cup', 1)],
        })
        cola_recipe = create_recipe(restaurant, {
            'catalog_item': str(catalog['COCA-COLA 0.5 L'].pk),
            'name': 'COCA-COLA 0.5 L ombor kartasi',
            'yield_quantity': '1',
            'trigger': 'sale',
            'lines': [base_line('cola', 1)],
        })

        def add_components(target, recipe, quantity, option_names=()):
            option_ids = {str(modifiers[name].pk) for name in option_names}
            for item_id, component_quantity in components_for(recipe, Decimal(str(quantity)), option_ids).items():
                target[item_id] += component_quantity

        def post_sales_day(day_index):
            totals = defaultdict(Decimal)
            add_components(totals, chicken_recipe, 7)
            add_components(totals, chicken_recipe, 2, ('Qo‘shimcha pishloq',))
            add_components(totals, chicken_recipe, 1, ('Bekon',))
            add_components(totals, chicken_recipe, 1, ('Piyozsiz', 'Soussiz'))
            add_components(totals, chicken_recipe, 1, ('Qo‘shimcha kotlet', 'Tuxum'))
            add_components(totals, classic_recipe, 5)
            add_components(totals, classic_recipe, 1, ('Qo‘shimcha pishloq',))
            add_components(totals, classic_recipe, 1, ('Bodringsiz',))
            add_components(totals, fries_recipe, 18)
            add_components(totals, cappuccino_recipe, 15)
            add_components(totals, cola_recipe, 10)
            self._post_system_sale(
                restaurant,
                sales_store,
                occurred(-16 + day_index, 21),
                f'KASSA-{(reference_date + timedelta(days=-16 + day_index)):%Y%m%d}-01',
                totals,
            )

        for day_index in range(12):
            post_sales_day(day_index)

        post('issue', sales_store, 'CHI-2609-014', occurred(-3, 22), [
            base_line('milk', 2000), base_line('greens', 300), base_line('bun', 5),
        ], reason='Sifat nazoratidan o‘tmagan mahsulotlarni hisobdan chiqarish',
             notes='Smena yopilishida dalolatnoma asosida chiqarildi.')

        def counted_line(key, actual):
            return {'item': str(items[key].pk), 'quantity': str(actual), 'input_unit': 'base'}

        first_actual = {
            'cheese': locked_balance(sales_store, items['cheese']).quantity - Decimal('5'),
            'bacon': locked_balance(sales_store, items['bacon']).quantity - Decimal('1000'),
            'sauce': locked_balance(sales_store, items['sauce']).quantity - Decimal('600'),
            'greens': locked_balance(sales_store, items['greens']).quantity - Decimal('200'),
            'coffee': locked_balance(sales_store, items['coffee']).quantity - Decimal('260'),
            'milk': locked_balance(sales_store, items['milk']).quantity - Decimal('400'),
        }
        post('stocktake', sales_store, 'INV-2609-01', occurred(-2, 23), [
            counted_line(key, value) for key, value in first_actual.items()
        ], reason='Haftalik nazorat sanog‘i', notes='Tortish va dona sanash natijalari.')
        second_cheese = locked_balance(sales_store, items['cheese']).quantity - Decimal('2')
        post('stocktake', sales_store, 'INV-2609-02', occurred(-1, 23), [
            counted_line('cheese', second_cheese),
        ], reason='Pishloq qoldig‘ini qayta nazorat qilish', notes='Smena almashinuvida qayta sanaldi.')

        balances = list(
            StockBalance.objects.filter(warehouse__restaurant=restaurant)
            .select_related('warehouse', 'item')
            .order_by('warehouse__name', 'item__name')
        )
        zero_items = [row.item.name for row in balances if row.warehouse_id == sales_store.pk and row.quantity == 0]
        balance_totals = {
            row['warehouse__name']: str(row['quantity'] or 0)
            for row in StockBalance.objects.filter(warehouse__restaurant=restaurant)
            .values('warehouse__name')
            .annotate(quantity=Count('id'))
            .order_by('warehouse__name')
        }
        return {
            'catalogRecipes': list(
                Recipe.objects.filter(restaurant=restaurant, catalog_item__isnull=False)
                .order_by('catalog_item__name')
                .values_list('catalog_item__name', flat=True)
            ),
            'zeroStockInSalesWarehouse': zero_items,
            'balanceRowsByWarehouse': balance_totals,
            'postedDocumentsByKind': {
                row['kind']: row['count']
                for row in StockDocument.objects.filter(restaurant=restaurant, status='posted')
                .values('kind').annotate(count=Count('id')).order_by('kind')
            },
        }

    @staticmethod
    def _post_system_sale(restaurant, warehouse, occurred_at, reference, components):
        document = make_document(
            restaurant,
            warehouse,
            StockDocument.Kind.SALE,
            reference=reference,
            reason='POS retseptlari bo‘yicha jamlangan sarf',
            responsible_name='Qamish kassasi',
            occurred_at=occurred_at,
            idempotency_key=f'qamish-seed:{reference}',
        )
        for item_id, quantity in sorted(components.items()):
            ingredient = InventoryItem.objects.get(pk=item_id, restaurant=restaurant)
            balance = locked_balance(warehouse, ingredient)
            if balance.quantity < quantity:
                raise CommandError(f'{ingredient.name}: sotuv simulyatsiyasi uchun qoldiq yetarli emas.')
            line = StockDocumentLine.objects.create(
                document=document,
                item=ingredient,
                item_name=ingredient.name,
                base_unit=ingredient.base_unit,
                quantity=quantity,
                base_quantity=quantity,
                unit_cost=balance.average_cost,
                base_unit_cost=balance.average_cost,
            )
            record_movement(document, line, -quantity, balance.average_cost)
        finish_document(document)
        return document
