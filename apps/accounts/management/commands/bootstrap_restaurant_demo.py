from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import BusinessPartnerUserProfile, RestaurantUserProfile, Role, User
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.integrations.services import ensure_mock_configs
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order, OrderItem, Payment, Receipt
from apps.organizations.models import (
    BusinessPartner,
    CashDesk,
    DistributionPoint,
    FeatureConfig,
    PrepStation,
    Restaurant,
    RestaurantEntitlement,
    Tariff,
)


def apply_translations(instance, field_name, translations):
    setattr(instance, field_name, translations['uz'])
    setattr(instance, f'{field_name}_uz', translations['uz'])
    setattr(instance, f'{field_name}_uz_crl', translations['uz_crl'])
    setattr(instance, f'{field_name}_ru', translations['ru'])


TARIFF_PRESET_SPECS = [
    {
        'key': 'fast_food',
        'name': 'Fast food',
        'description': "Zalsiz, faqat menyu va kassada ishlaydigan nuqtalar uchun.",
        'classification': Tariff.Classification.BASIC,
        'monthly_price': 490000,
        'yearly_price': 4900000,
        'operational_settings': {
            'hall_enabled': False,
            'kitchen_enabled': False,
            'cashier_enabled': True,
            'owner_dashboard_enabled': True,
            'order_entry_mode': 'cashier_builder',
            'kitchen_mode': 'display',
            'enabled_modules': ['cashier', 'owner_dashboard'],
            'enabled_roles': ['owner', 'admin', 'manager', 'cashier', 'universal_operator'],
        },
    },
    {
        'key': 'printer_kitchen',
        'name': 'Printer kitchen',
        'description': 'Zal va kassa bor, buyurtma oshxonaga printer orqali ketadigan restoranlar uchun.',
        'classification': Tariff.Classification.STANDARD,
        'monthly_price': 790000,
        'yearly_price': 7900000,
        'operational_settings': {
            'hall_enabled': True,
            'kitchen_enabled': True,
            'cashier_enabled': True,
            'owner_dashboard_enabled': True,
            'order_entry_mode': 'hall',
            'kitchen_mode': 'printer',
            'enabled_modules': ['hall', 'kitchen', 'cashier', 'owner_dashboard'],
            'enabled_roles': ['owner', 'admin', 'manager', 'waiter', 'cashier', 'universal_operator'],
        },
    },
    {
        'key': 'full_service',
        'name': 'Full service',
        'description': 'Zal, oshxona va kassa bilan ishlaydigan oddiy restoranlar uchun.',
        'classification': Tariff.Classification.PREMIUM,
        'monthly_price': 990000,
        'yearly_price': 9900000,
        'operational_settings': {
            'hall_enabled': True,
            'kitchen_enabled': True,
            'cashier_enabled': True,
            'owner_dashboard_enabled': True,
            'order_entry_mode': 'hall',
            'kitchen_mode': 'display',
            'enabled_modules': ['hall', 'kitchen', 'cashier', 'owner_dashboard'],
            'enabled_roles': ['owner', 'admin', 'manager', 'waiter', 'cashier', 'chef', 'barman', 'universal_operator'],
        },
    },
]

FULL_SERVICE_DEMO_ENTITLEMENT_SETTINGS = {
    'hall_enabled': True,
    'kitchen_enabled': True,
    'cashier_enabled': True,
    'owner_dashboard_enabled': True,
    'reports_enabled': True,
}


ZONE_NAMES = ['1-qavat', '2-qavat']


HALL_SPECS = [
    {
        'code': 'main-hall',
        'name': {'uz': 'Asosiy zal', 'uz_crl': 'Асосий зал', 'ru': 'Основной зал'},
        'description': {
            'uz': 'Asosiy mehmonlar oqimi uchun zal',
            'uz_crl': 'Асосий меҳмонлар оқими учун зал',
            'ru': 'Зал для основного потока гостей',
        },
        'sort_order': 1,
    },
    {
        'code': 'family-hall',
        'name': {'uz': 'Oilaviy zal', 'uz_crl': 'Оилавий зал', 'ru': 'Семейный зал'},
        'description': {
            'uz': 'Oilaviy va tinch o‘tirish hududi',
            'uz_crl': 'Оилавий ва тинч ўтириш ҳудуди',
            'ru': 'Спокойная зона для семейных гостей',
        },
        'sort_order': 2,
    },
    {
        'code': 'vip-hall',
        'name': {'uz': 'VIP zal', 'uz_crl': 'VIP зал', 'ru': 'VIP зал'},
        'description': {
            'uz': 'Yopiq va xususiy xizmat hududi',
            'uz_crl': 'Ёпиқ ва хусусий хизмат ҳудуди',
            'ru': 'Закрытая зона для приватного обслуживания',
        },
        'sort_order': 3,
    },
    {
        'code': 'small-hall',
        'name': {'uz': 'Kichik zal', 'uz_crl': 'Кичик зал', 'ru': 'Малый зал'},
        'description': {
            'uz': 'Tez xizmat uchun ixcham zal',
            'uz_crl': 'Тез хизмат учун ихчам зал',
            'ru': 'Компактный зал для быстрого обслуживания',
        },
        'sort_order': 4,
    },
    {
        'code': 'terrace',
        'name': {'uz': 'Terassa', 'uz_crl': 'Терасса', 'ru': 'Терраса'},
        'description': {
            'uz': 'Ochiq havodagi stol hududi',
            'uz_crl': 'Очиқ ҳаводаги стол ҳудуди',
            'ru': 'Открытая терраса со столами',
        },
        'sort_order': 5,
    },
    {
        'code': 'main-hall-l2',
        'name': {'uz': 'Asosiy zal', 'uz_crl': 'РђСЃРѕСЃРёР№ Р·Р°Р»', 'ru': 'РћСЃРЅРѕРІРЅРѕР№ Р·Р°Р»'},
        'description': {
            'uz': 'Ikkinchi qavat asosiy mehmonlar zali',
            'uz_crl': 'РРєРєРёРЅС‡Рё Т›Р°РІР°С‚ Р°СЃРѕСЃРёР№ РјРµТіРјРѕРЅР»Р°СЂ Р·Р°Р»Рё',
            'ru': 'РћСЃРЅРѕРІРЅРѕР№ Р·Р°Р» РЅР° РІС‚РѕСЂРѕРј СЌС‚Р°Р¶Рµ',
        },
        'sort_order': 1,
    },
    {
        'code': 'vip-hall-l2',
        'name': {'uz': 'VIP zal', 'uz_crl': 'VIP Р·Р°Р»', 'ru': 'VIP Р·Р°Р»'},
        'description': {
            'uz': 'Ikkinchi qavat xususiy xizmat zali',
            'uz_crl': 'РРєРєРёРЅС‡Рё Т›Р°РІР°С‚ С…СѓСЃСѓСЃРёР№ С…РёР·РјР°С‚ Р·Р°Р»Рё',
            'ru': 'Р—Р°Р» РїСЂРёРІР°С‚РЅРѕРіРѕ РѕР±СЃР»СѓР¶РёРІР°РЅРёСЏ РЅР° РІС‚РѕСЂРѕРј СЌС‚Р°Р¶Рµ',
        },
        'sort_order': 2,
    },
]

CATEGORY_SPECS = [
    {'code': 'salatlar', 'mxik_code': '10000000000000001', 'sort_order': 1, 'name': {'uz': 'Salatlar', 'uz_crl': 'Салатлар', 'ru': 'Салаты'}},
    {'code': 'shorvalar', 'mxik_code': '10000000000000002', 'sort_order': 2, 'name': {'uz': 'Sho‘rvalar', 'uz_crl': 'Шўрвалар', 'ru': 'Супы'}},
    {'code': 'asosiy-taomlar', 'mxik_code': '10000000000000003', 'sort_order': 3, 'name': {'uz': 'Asosiy taomlar', 'uz_crl': 'Асосий таомлар', 'ru': 'Основные блюда'}},
    {'code': 'kaboblar', 'mxik_code': '10000000000000004', 'sort_order': 4, 'name': {'uz': 'Kaboblar', 'uz_crl': 'Кабоблар', 'ru': 'Шашлыки'}},
    {'code': 'shirinliklar', 'mxik_code': '10000000000000005', 'sort_order': 5, 'name': {'uz': 'Shirinliklar', 'uz_crl': 'Ширинликлар', 'ru': 'Десерты'}},
    {'code': 'issiq-ichimliklar', 'mxik_code': '10000000000000006', 'sort_order': 6, 'name': {'uz': 'Issiq ichimliklar', 'uz_crl': 'Иссиқ ичимликлар', 'ru': 'Горячие напитки'}},
    {'code': 'sovuq-ichimliklar', 'mxik_code': '10000000000000007', 'sort_order': 7, 'name': {'uz': 'Sovuq ichimliklar', 'uz_crl': 'Совуқ ичимликлар', 'ru': 'Холодные напитки'}},
]

CATALOG_ITEM_SPECS = [
    {
        'code': 'achchiq-chuchuk',
        'category_code': 'salatlar',
                'prep_station_code': 'kitchen',
        'price': 18000,
        'name': {'uz': 'Achchiq-chuchuk', 'uz_crl': 'Аччиқ-чучук', 'ru': 'Аччик-чучук'},
        'description': {'uz': 'Pomidor va piyozli yangi salat', 'uz_crl': 'Помидор ва пиёзли янги салат', 'ru': 'Свежий салат с помидорами и луком'},
    },
    {
        'code': 'olivye',
        'category_code': 'salatlar',
                'prep_station_code': 'kitchen',
        'price': 24000,
        'name': {'uz': 'Olivye', 'uz_crl': 'Оливье', 'ru': 'Оливье'},
        'description': {'uz': 'Mayin va to‘yimli salat', 'uz_crl': 'Майин ва тўйимли салат', 'ru': 'Нежный и сытный салат'},
    },
    {
        'code': 'sezar-salat',
        'category_code': 'salatlar',
                'prep_station_code': 'kitchen',
        'price': 34000,
        'name': {'uz': 'Sezar salat', 'uz_crl': 'Сезар салат', 'ru': 'Салат Цезарь'},
        'description': {'uz': 'Tovuq va parmesan bilan', 'uz_crl': 'Товуқ ва пармезан билан', 'ru': 'С курицей и пармезаном'},
    },
    {
        'code': 'mastava',
        'category_code': 'shorvalar',
                'prep_station_code': 'kitchen',
        'price': 24000,
        'name': {'uz': 'Mastava', 'uz_crl': 'Мастава', 'ru': 'Мастава'},
        'description': {'uz': 'Guruchli an’anaviy sho‘rva', 'uz_crl': 'Гуручли анъанавий шўрва', 'ru': 'Традиционный рисовый суп'},
    },
    {
        'code': 'moshxorda',
        'category_code': 'shorvalar',
                'prep_station_code': 'kitchen',
        'price': 23000,
        'name': {'uz': 'Moshxo‘rda', 'uz_crl': 'Мошхўрда', 'ru': 'Мошхурда'},
        'description': {'uz': 'Mosh va guruchli sho‘rva', 'uz_crl': 'Мош ва гуручли шўрва', 'ru': 'Суп с машем и рисом'},
    },
    {
        'code': 'chuchvara-shorva',
        'category_code': 'shorvalar',
                'prep_station_code': 'kitchen',
        'price': 26000,
        'name': {'uz': 'Chuchvara sho‘rva', 'uz_crl': 'Чучвара шўрва', 'ru': 'Суп с чучварой'},
        'description': {'uz': 'Mayda chuchvarali sho‘rva', 'uz_crl': 'Майда чучваралик шўрва', 'ru': 'Суп с маленькими пельменями'},
    },
    {
        'code': 'osh',
        'category_code': 'asosiy-taomlar',
                'prep_station_code': 'kitchen',
        'price': 32000,
        'name': {'uz': 'Osh', 'uz_crl': 'Ош', 'ru': 'Плов'},
        'description': {'uz': 'An’anaviy to‘y oshi', 'uz_crl': 'Анъанавий тўй оши', 'ru': 'Традиционный праздничный плов'},
    },
    {
        'code': 'manti',
        'category_code': 'asosiy-taomlar',
                'prep_station_code': 'kitchen',
        'price': 28000,
        'name': {'uz': 'Manti', 'uz_crl': 'Манти', 'ru': 'Манты'},
        'description': {'uz': 'Qo‘l usulida tayyorlangan manti', 'uz_crl': 'Қўл усулида тайёрланган манти', 'ru': 'Манты ручной лепки'},
    },
    {
        'code': 'lagmon',
        'category_code': 'asosiy-taomlar',
                'prep_station_code': 'kitchen',
        'price': 36000,
        'name': {'uz': 'Lag‘mon', 'uz_crl': 'Лагмон', 'ru': 'Лагман'},
        'description': {'uz': 'Cho‘zma xamirli issiq taom', 'uz_crl': 'Чўзма хамирли иссиқ таом', 'ru': 'Горячее блюдо с тянутой лапшой'},
    },
    {
        'code': 'qozon-kabob',
        'category_code': 'asosiy-taomlar',
                'prep_station_code': 'grill',
        'price': 46000,
        'name': {'uz': 'Qozon kabob', 'uz_crl': 'Қозон кабоб', 'ru': 'Казан-кебаб'},
        'description': {'uz': 'Kartoshka va go‘sht bilan', 'uz_crl': 'Картошка ва гўшт билан', 'ru': 'С картофелем и мясом'},
    },
    {
        'code': 'dimlama',
        'category_code': 'asosiy-taomlar',
                'prep_station_code': 'kitchen',
        'price': 39000,
        'name': {'uz': 'Dimlama', 'uz_crl': 'Димлама', 'ru': 'Димлама'},
        'description': {'uz': 'Sabzavotli dimlama', 'uz_crl': 'Сабзавотли димлама', 'ru': 'Томленое блюдо с овощами'},
    },
    {
        'code': 'tovuq-shashlik',
        'category_code': 'kaboblar',
                'prep_station_code': 'grill',
        'price': 26000,
        'name': {'uz': 'Tovuq shashlik', 'uz_crl': 'Товуқ шашлик', 'ru': 'Куриный шашлык'},
        'description': {'uz': 'Yumshoq marinadlangan tovuq', 'uz_crl': 'Юмшоқ маринадланган товуқ', 'ru': 'Мягкая маринованная курица'},
    },
    {
        'code': 'mol-shashlik',
        'category_code': 'kaboblar',
                'prep_station_code': 'grill',
        'price': 34000,
        'name': {'uz': 'Mol shashlik', 'uz_crl': 'Мол шашлик', 'ru': 'Говяжий шашлык'},
        'description': {'uz': 'Mol go‘shtidan kabob', 'uz_crl': 'Мол гўштидан кабоб', 'ru': 'Шашлык из говядины'},
    },
    {
        'code': 'qiymali-kabob',
        'category_code': 'kaboblar',
                'prep_station_code': 'grill',
        'price': 31000,
        'name': {'uz': 'Qiymali kabob', 'uz_crl': 'Қиймали кабоб', 'ru': 'Люля-кебаб'},
        'description': {'uz': 'Sharqona ziravorlar bilan', 'uz_crl': 'Шарқона зираворлар билан', 'ru': 'С восточными специями'},
    },
    {
        'code': 'qanotcha',
        'category_code': 'kaboblar',
                'prep_station_code': 'grill',
        'price': 29000,
        'name': {'uz': 'Qanotcha', 'uz_crl': 'Қанотча', 'ru': 'Крылышки на гриле'},
        'description': {'uz': 'Achchiq sousli qanotcha', 'uz_crl': 'Аччиқ соусли қанотча', 'ru': 'Крылышки в пикантном соусе'},
    },
    {
        'code': 'chak-chak',
        'category_code': 'shirinliklar',
                'prep_station_code': 'kitchen',
        'price': 16000,
        'name': {'uz': 'Chak-chak', 'uz_crl': 'Чак-чак', 'ru': 'Чак-чак'},
        'description': {'uz': 'Asalli sharqona shirinlik', 'uz_crl': 'Асалли шарқона ширинлик', 'ru': 'Восточная сладость с медом'},
    },
    {
        'code': 'medovik',
        'category_code': 'shirinliklar',
                'prep_station_code': 'kitchen',
        'price': 21000,
        'name': {'uz': 'Medovik', 'uz_crl': 'Медовик', 'ru': 'Медовик'},
        'description': {'uz': 'Qatlamli asal torti', 'uz_crl': 'Қатламли асал торти', 'ru': 'Слоеный медовый торт'},
    },
    {
        'code': 'napoleon',
        'category_code': 'shirinliklar',
                'prep_station_code': 'kitchen',
        'price': 19000,
        'name': {'uz': 'Napoleon', 'uz_crl': 'Наполеон', 'ru': 'Наполеон'},
        'description': {'uz': 'Yengil qaymoqli tort', 'uz_crl': 'Енгил қаймоқли торт', 'ru': 'Легкий торт с кремом'},
    },
    {
        'code': 'kuk-choy',
        'category_code': 'issiq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 12000,
        'name': {'uz': 'Ko‘k choy', 'uz_crl': 'Кўк чой', 'ru': 'Зеленый чай'},
        'description': {'uz': 'Choynakda tortiladi', 'uz_crl': 'Чойнакда тортилади', 'ru': 'Подается в чайнике'},
    },
    {
        'code': 'qora-choy',
        'category_code': 'issiq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 12000,
        'name': {'uz': 'Qora choy', 'uz_crl': 'Қора чой', 'ru': 'Черный чай'},
        'description': {'uz': 'Limon bilan ham beriladi', 'uz_crl': 'Лимон билан ҳам берилади', 'ru': 'Можно подать с лимоном'},
    },
    {
        'code': 'espresso',
        'category_code': 'issiq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 14000,
        'name': {'uz': 'Espresso', 'uz_crl': 'Эспрессо', 'ru': 'Эспрессо'},
        'description': {'uz': 'Kuchli qahva porsiyasi', 'uz_crl': 'Кучли қаҳва порцияси', 'ru': 'Крепкая порция кофе'},
    },
    {
        'code': 'kapuchino',
        'category_code': 'issiq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 19000,
        'name': {'uz': 'Kapuchino', 'uz_crl': 'Капучино', 'ru': 'Капучино'},
        'description': {'uz': 'Sut ko‘pigili qahva', 'uz_crl': 'Сут кўпигили қаҳва', 'ru': 'Кофе с молочной пеной'},
    },
    {
        'code': 'limonad',
        'category_code': 'sovuq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 16000,
        'name': {'uz': 'Limonad', 'uz_crl': 'Лимонад', 'ru': 'Лимонад'},
        'description': {'uz': 'Uy usulida tayyorlangan', 'uz_crl': 'Уй усулида тайёрланган', 'ru': 'Домашний лимонад'},
    },
    {
        'code': 'mors',
        'category_code': 'sovuq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 15000,
        'name': {'uz': 'Mors', 'uz_crl': 'Морс', 'ru': 'Морс'},
        'description': {'uz': 'Mevali sovuq ichimlik', 'uz_crl': 'Мевали совуқ ичимлик', 'ru': 'Холодный ягодный напиток'},
    },
    {
        'code': 'ayran',
        'category_code': 'sovuq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 11000,
        'name': {'uz': 'Ayran', 'uz_crl': 'Айран', 'ru': 'Айран'},
        'description': {'uz': 'Sovuq sutli ichimlik', 'uz_crl': 'Совуқ сутли ичимлик', 'ru': 'Холодный кисломолочный напиток'},
    },
    {
        'code': 'anor-sharbati',
        'category_code': 'sovuq-ichimliklar',
                'prep_station_code': 'bar',
        'price': 24000,
        'name': {'uz': 'Anor sharbati', 'uz_crl': 'Анор шарбати', 'ru': 'Гранатовый сок'},
        'description': {'uz': 'Yangi siqilgan sharbat', 'uz_crl': 'Янги сиқилган шарбат', 'ru': 'Свежевыжатый сок'},
    },
]

def build_table_spec(
    table_number,
    *,
    seat_count,
    position_x,
    position_y,
    width=1,
    height=1,
    status=DiningTable.Status.AVAILABLE,
    shape_variant=None,
):
    shape_variant = shape_variant or DiningTable.get_default_shape_variant(seat_count)
    return {
        'table_number': table_number,
        'seat_count': seat_count,
        'shape': DiningTable.infer_shape_from_variant(shape_variant),
        'shape_variant': shape_variant,
        'status': status,
        'position_x': position_x,
        'position_y': position_y,
        'width': width,
        'height': height,
    }


HALL_GRID_COLUMNS = {
    'main-hall': 8,
    'family-hall': 4,
    'vip-hall': 3,
    'small-hall': 4,
    'terrace': 4,
    'main-hall-l2': 6,
    'vip-hall-l2': 3,
}

DEFAULT_ZONE_NAMES = ['1-qavat', '2-qavat', 'Kabina 1', 'Kabina 2']


MAIN_HALL_TABLE_SPECS = [
    *[
        build_table_spec(
            table_number,
            seat_count=2,
            position_x=(table_number - 1) % 8,
            position_y=(table_number - 1) // 8,
            status={
                3: DiningTable.Status.OCCUPIED,
                6: DiningTable.Status.OCCUPIED,
                7: DiningTable.Status.BLOCKED,
                10: DiningTable.Status.OCCUPIED,
                12: DiningTable.Status.BLOCKED,
                16: DiningTable.Status.OCCUPIED,
            }.get(table_number, DiningTable.Status.AVAILABLE),
            shape_variant=(
                DiningTable.ShapeVariant.SEAT2_HORIZONTAL
                if table_number <= 8
                else DiningTable.ShapeVariant.SEAT2_VERTICAL
            ),
        )
        for table_number in range(1, 17)
    ],
    *[
        build_table_spec(
            table_number,
            seat_count=4,
            position_x=(table_number - 17) % 8,
            position_y=2 + (((table_number - 17) // 8) * 2),
            width=1,
            height=2,
            status={
                17: DiningTable.Status.OCCUPIED,
                27: DiningTable.Status.OCCUPIED,
                30: DiningTable.Status.OCCUPIED,
            }.get(table_number, DiningTable.Status.AVAILABLE),
            shape_variant=DiningTable.ShapeVariant.SEAT4_VERTICAL,
        )
        for table_number in range(17, 33)
    ],
]

SECONDARY_HALL_TABLE_SPECS = {
    'family-hall': [
        build_table_spec(table_number, seat_count=4, position_x=(table_number - 1) % 4, position_y=(table_number - 1) // 4, shape_variant=DiningTable.ShapeVariant.SEAT4_HORIZONTAL)
        for table_number in range(1, 13)
    ],
    'vip-hall': [
        build_table_spec(table_number, seat_count=6, position_x=(table_number - 1) % 3, position_y=(table_number - 1) // 3, shape_variant=DiningTable.ShapeVariant.SEAT6_HORIZONTAL)
        for table_number in range(1, 7)
    ],
    'small-hall': [
        build_table_spec(
            table_number,
            seat_count=2,
            position_x=(table_number - 1) % 4,
            position_y=(table_number - 1) // 4,
            shape_variant=DiningTable.ShapeVariant.SEAT2_VERTICAL if table_number % 2 == 0 else DiningTable.ShapeVariant.SEAT2_HORIZONTAL,
        )
        for table_number in range(1, 9)
    ],
    'terrace': [
        build_table_spec(
            table_number,
            seat_count=4,
            position_x=(table_number - 1) % 4,
            position_y=(table_number - 1) // 4,
            shape_variant=DiningTable.ShapeVariant.SEAT4_VERTICAL if table_number % 2 == 0 else DiningTable.ShapeVariant.SEAT4_SQUARE,
        )
        for table_number in range(1, 9)
    ],
    'main-hall-l2': [
        build_table_spec(
            table_number,
            seat_count=4,
            position_x=(table_number - 1) % 6,
            position_y=(table_number - 1) // 6,
            shape_variant=DiningTable.ShapeVariant.SEAT4_SQUARE if table_number % 2 else DiningTable.ShapeVariant.SEAT4_HORIZONTAL,
        )
        for table_number in range(1, 13)
    ],
    'vip-hall-l2': [
        build_table_spec(
            table_number,
            seat_count=6,
            position_x=(table_number - 1) % 3,
            position_y=(table_number - 1) // 3,
            shape_variant=DiningTable.ShapeVariant.SEAT6_HORIZONTAL if table_number % 2 else DiningTable.ShapeVariant.SEAT6_VERTICAL,
        )
        for table_number in range(1, 7)
    ],
}

DEMO_ORDERS = [
    {'hall_code': 'family-hall', 'table_no': 2, 'waiter': 'waiter', 'item_codes': ['mastava', 'lagmon', 'limonad'], 'minutes_ago': 137, 'closed': True},
    {'hall_code': 'vip-hall', 'table_no': 1, 'waiter': 'waiter2', 'item_codes': ['sezar-salat', 'mol-shashlik', 'anor-sharbati'], 'minutes_ago': 112, 'closed': True},
    {'hall_code': 'small-hall', 'table_no': 3, 'waiter': 'waiter', 'item_codes': ['manti', 'ayran'], 'minutes_ago': 96, 'closed': True},
    {
        'channel': Order.Channel.TAKEAWAY,
        'waiter': 'waiter',
        'item_codes': ['osh', 'limonad'],
        'minutes_ago': 88,
        'closed': True,
        'guest_count': 1,
    },
    {
        'channel': Order.Channel.TAKEAWAY,
        'waiter': 'waiter2',
        'item_codes': ['qozon-kabob', 'kapuchino'],
        'minutes_ago': 74,
        'closed': True,
        'guest_count': 1,
    },
    {'hall_code': 'main-hall', 'table_no': 3, 'waiter': 'waiter', 'item_codes': ['achchiq-chuchuk', 'mors'], 'minutes_ago': 31, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {'hall_code': 'main-hall', 'table_no': 6, 'waiter': 'waiter2', 'item_codes': ['lagmon', 'kuk-choy'], 'minutes_ago': 206, 'closed': False, 'ticket_status': KitchenTicket.Status.COOKING},
    {
        'hall_code': 'main-hall',
        'table_no': 7,
        'waiter': 'waiter',
        'item_codes': ['qozon-kabob', 'anor-sharbati'],
        'minutes_ago': 18,
        'closed': False,
        'session_status': TableSession.Status.PENDING_PAYMENT,
        'ticket_status': KitchenTicket.Status.DONE,
    },
    {'hall_code': 'main-hall', 'table_no': 10, 'waiter': 'waiter2', 'item_codes': ['moshxorda', 'limonad'], 'minutes_ago': 42, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {
        'hall_code': 'main-hall',
        'table_no': 12,
        'waiter': 'waiter',
        'item_codes': ['dimlama', 'qora-choy'],
        'minutes_ago': 25,
        'closed': False,
        'session_status': TableSession.Status.PENDING_PAYMENT,
        'ticket_status': KitchenTicket.Status.DONE,
    },
    {'hall_code': 'main-hall', 'table_no': 16, 'waiter': 'waiter2', 'item_codes': ['manti', 'espresso'], 'minutes_ago': 206, 'closed': False, 'ticket_status': KitchenTicket.Status.COOKING},
    {'hall_code': 'main-hall', 'table_no': 17, 'waiter': 'waiter', 'item_codes': ['osh', 'kuk-choy'], 'minutes_ago': 64, 'closed': False, 'ticket_status': KitchenTicket.Status.DONE},
    {'hall_code': 'main-hall', 'table_no': 27, 'waiter': 'waiter', 'item_codes': ['chak-chak', 'kapuchino'], 'minutes_ago': 41, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {'hall_code': 'main-hall', 'table_no': 30, 'waiter': 'waiter2', 'item_codes': ['olivye', 'osh', 'limonad'], 'minutes_ago': 34, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {'hall_code': 'terrace', 'table_no': 3, 'waiter': 'waiter', 'item_codes': ['anor-sharbati', 'medovik'], 'minutes_ago': 22, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {'hall_code': 'family-hall', 'table_no': 7, 'waiter': 'waiter2', 'item_codes': ['chuchvara-shorva', 'manti', 'kuk-choy'], 'minutes_ago': 18, 'closed': False, 'ticket_status': KitchenTicket.Status.NEW},
    {'hall_code': 'vip-hall', 'table_no': 4, 'waiter': 'waiter', 'item_codes': ['sezar-salat', 'qanotcha', 'espresso'], 'minutes_ago': 12, 'closed': False, 'ticket_status': KitchenTicket.Status.COOKING},
    {
        'channel': Order.Channel.TAKEAWAY,
        'waiter': 'waiter',
        'item_codes': ['lagmon', 'kuk-choy'],
        'minutes_ago': 15,
        'closed': False,
        'guest_count': 1,
        'ticket_status': KitchenTicket.Status.NEW,
    },
    {
        'channel': Order.Channel.TAKEAWAY,
        'waiter': 'waiter2',
        'item_codes': ['sezar-salat', 'espresso'],
        'minutes_ago': 8,
        'closed': False,
        'guest_count': 1,
        'ticket_status': KitchenTicket.Status.COOKING,
    },
]

HISTORY_LOOKBACK_DAYS = 60

HISTORICAL_ORDER_PATTERNS = [
    {'hall_code': 'main-hall', 'table_no': 2, 'waiter': 'waiter', 'item_codes': ['osh', 'qora-choy'], 'guest_count': 2, 'minute_of_day': 11 * 60 + 20},
    {'hall_code': 'main-hall', 'table_no': 8, 'waiter': 'waiter2', 'item_codes': ['mastava', 'manti', 'limonad'], 'guest_count': 3, 'minute_of_day': 12 * 60 + 45},
    {'hall_code': 'main-hall', 'table_no': 14, 'waiter': 'waiter', 'item_codes': ['lagmon', 'kuk-choy'], 'guest_count': 2, 'minute_of_day': 14 * 60 + 10},
    {'hall_code': 'main-hall', 'table_no': 21, 'waiter': 'waiter2', 'item_codes': ['qozon-kabob', 'ayran', 'chak-chak'], 'guest_count': 4, 'minute_of_day': 18 * 60 + 5},
    {'hall_code': 'family-hall', 'table_no': 4, 'waiter': 'waiter', 'item_codes': ['chuchvara-shorva', 'manti', 'qora-choy'], 'guest_count': 3, 'minute_of_day': 13 * 60 + 25},
    {'hall_code': 'family-hall', 'table_no': 9, 'waiter': 'waiter2', 'item_codes': ['osh', 'limonad', 'medovik'], 'guest_count': 4, 'minute_of_day': 19 * 60 + 10},
    {'hall_code': 'vip-hall', 'table_no': 2, 'waiter': 'waiter', 'item_codes': ['sezar-salat', 'mol-shashlik', 'anor-sharbati'], 'guest_count': 3, 'minute_of_day': 20 * 60},
    {'hall_code': 'small-hall', 'table_no': 5, 'waiter': 'waiter2', 'item_codes': ['dimlama', 'mors'], 'guest_count': 2, 'minute_of_day': 12 * 60 + 5},
    {'hall_code': 'terrace', 'table_no': 5, 'waiter': 'waiter', 'item_codes': ['achchiq-chuchuk', 'tovuq-shashlik', 'limonad'], 'guest_count': 3, 'minute_of_day': 17 * 60 + 35},
    {'hall_code': 'main-hall-l2', 'table_no': 6, 'waiter': 'waiter2', 'item_codes': ['moshxorda', 'osh', 'kuk-choy'], 'guest_count': 3, 'minute_of_day': 15 * 60 + 20},
    {'hall_code': 'vip-hall-l2', 'table_no': 3, 'waiter': 'waiter', 'item_codes': ['sezar-salat', 'qanotcha', 'espresso'], 'guest_count': 2, 'minute_of_day': 21 * 60 + 15},
    {'hall_code': 'terrace', 'table_no': 7, 'waiter': 'waiter2', 'item_codes': ['qanotcha', 'anor-sharbati'], 'guest_count': 2, 'minute_of_day': 16 * 60 + 40},
    {'channel': Order.Channel.TAKEAWAY, 'waiter': 'waiter', 'item_codes': ['osh', 'mors'], 'guest_count': 1, 'minute_of_day': 10 * 60 + 35},
    {'channel': Order.Channel.TAKEAWAY, 'waiter': 'waiter2', 'item_codes': ['manti', 'qora-choy'], 'guest_count': 1, 'minute_of_day': 13 * 60 + 50},
    {'channel': Order.Channel.TAKEAWAY, 'waiter': 'waiter', 'item_codes': ['qanotcha', 'limonad'], 'guest_count': 1, 'minute_of_day': 19 * 60 + 45},
]


def set_model_timestamps(instance, **timestamps):
    instance.__class__.objects.filter(pk=instance.pk).update(**timestamps)
    for field_name, value in timestamps.items():
        setattr(instance, field_name, value)


def build_historical_demo_orders(now):
    historical_orders = []
    for days_ago in range(HISTORY_LOOKBACK_DAYS, -1, -1):
        day_patterns_count = 3 + (days_ago % 2)
        for offset in range(day_patterns_count):
            pattern = HISTORICAL_ORDER_PATTERNS[(days_ago + offset) % len(HISTORICAL_ORDER_PATTERNS)]
            opened_day = (now - timedelta(days=days_ago)).replace(second=0, microsecond=0)
            minute_of_day = (pattern['minute_of_day'] + (days_ago % 5) * 7 + offset * 11) % (22 * 60)
            opened_at = opened_day.replace(hour=minute_of_day // 60, minute=minute_of_day % 60)
            historical_orders.append(
                {
                    **pattern,
                    'closed': True,
                    'opened_at': opened_at,
                    'close_after_minutes': 36 + ((days_ago + offset) % 5) * 6,
                    'payment_delay_minutes': 30 + ((days_ago + offset) % 4) * 4,
                }
            )
    return historical_orders


def build_demo_orders(now):
    return [*build_historical_demo_orders(now), *DEMO_ORDERS]


class Command(BaseCommand):
    help = "Realistik restoran demo ma'lumotlarini yaratadi."

    def handle(self, *args, **options):
        business_partner, _ = BusinessPartner.objects.get_or_create(
            inn='309876543',
            defaults={
                'company_name': 'Postcode hamkor',
                'status': BusinessPartner.Status.ACTIVE,
            },
        )
        business_partner.company_name = 'Postcode hamkor'
        business_partner.legal_name = 'Postcode hamkor MCHJ'
        business_partner.phone = '+998901234567'
        business_partner.email = 'partner.demo@postcode.uz'
        business_partner.address = 'Toshkent shahri, Yunusobod tumani'
        business_partner.status = BusinessPartner.Status.ACTIVE
        business_partner.activated_at = timezone.now()
        business_partner.save()

        tariffs_by_key = {}
        for tariff_spec in TARIFF_PRESET_SPECS:
            tariff, _ = Tariff.objects.get_or_create(
                name=tariff_spec['name'],
                defaults={
                    'classification': tariff_spec['classification'],
                    'monthly_price': tariff_spec['monthly_price'],
                    'yearly_price': tariff_spec['yearly_price'],
                    'is_active': True,
                },
            )
            tariff.classification = tariff_spec['classification']
            tariff.description = tariff_spec['description']
            tariff.monthly_price = tariff_spec['monthly_price']
            tariff.yearly_price = tariff_spec['yearly_price']
            tariff.is_active = True
            tariff.operational_settings = dict(tariff_spec['operational_settings'])
            tariff.save()
            tariffs_by_key[tariff_spec['key']] = tariff

        full_service_tariff = tariffs_by_key['full_service']

        restaurant, _ = Restaurant.objects.get_or_create(name='Postcode kafe')
        restaurant.business_partner = business_partner
        apply_translations(restaurant, 'name', {'uz': 'Postcode kafe', 'uz_crl': 'Postcode кафе', 'ru': 'Postcode кафе'})
        apply_translations(
            restaurant,
            'legal_name',
            {'uz': 'Postcode kafe MCHJ', 'uz_crl': 'Postcode кафе МЧЖ', 'ru': 'ООО Postcode кафе'},
        )
        apply_translations(
            restaurant,
            'address',
            {'uz': 'Yunusobod tumani, Toshkent', 'uz_crl': 'Юнусобод тумани, Тошкент', 'ru': 'Юнусабадский район, Ташкент'},
        )
        restaurant.save()

        entitlement, _ = RestaurantEntitlement.objects.get_or_create(restaurant=restaurant)
        entitlement.tariff = full_service_tariff
        entitlement.is_active = True
        entitlement.is_custom = False
        entitlement.starts_on = timezone.localdate()
        entitlement.monthly_price = full_service_tariff.monthly_price
        entitlement.yearly_price = full_service_tariff.yearly_price
        entitlement.operational_settings = dict(FULL_SERVICE_DEMO_ENTITLEMENT_SETTINGS)
        entitlement.save()

        Tariff.objects.filter(name='Demo tarif', restaurant_entitlements__isnull=True).delete()

        KitchenTicket.objects.filter(restaurant=restaurant).delete()
        Order.objects.filter(restaurant=restaurant).delete()
        TableSession.objects.filter(restaurant=restaurant).delete()
        Hall.objects.filter(restaurant=restaurant).delete()
        CatalogItem.objects.filter(restaurant=restaurant).delete()
        CatalogCategory.objects.filter(restaurant=restaurant).delete()
        DistributionPoint.objects.filter(restaurant=restaurant).delete()
        CashDesk.objects.filter(restaurant=restaurant).delete()

        feature_config, _ = FeatureConfig.objects.get_or_create(restaurant=restaurant)
        feature_config.kitchen_mode = FeatureConfig.KitchenMode.BOTH
        feature_config.hall_enabled = True
        feature_config.kitchen_enabled = True
        feature_config.cashier_enabled = True
        feature_config.owner_dashboard_enabled = True
        feature_config.order_entry_mode = FeatureConfig.OrderEntryMode.HALL
        feature_config.save()

        prep_station_specs = [
            {'code': 'kitchen', 'kind': PrepStation.Kind.KITCHEN, 'name': {'uz': 'Asosiy oshxona', 'uz_crl': 'Асосий ошхона', 'ru': 'Основная кухня'}},
            {'code': 'bar', 'kind': PrepStation.Kind.BAR, 'name': {'uz': 'Bar', 'uz_crl': 'Бар', 'ru': 'Бар'}},
            {'code': 'grill', 'kind': PrepStation.Kind.OTHER, 'name': {'uz': 'Gril nuqtasi', 'uz_crl': 'Грил нуқтаси', 'ru': 'Гриль станция'}},
        ]
        prep_stations = {}
        for spec in prep_station_specs:
            station, _ = PrepStation.objects.get_or_create(
                restaurant=restaurant,
                name=spec['name']['uz'],
                defaults={'kind': spec['kind']},
            )
            station.kind = spec['kind']
            apply_translations(station, 'name', spec['name'])
            station.save()
            prep_stations[spec['code']] = station

        main_cash_desk = CashDesk.objects.create(
            restaurant=restaurant,
            name='Asosiy kassa',
            location='Kirish qismi',
        )

        hall_distribution = DistributionPoint.objects.create(
            restaurant=restaurant,
            kind=DistributionPoint.Kind.HALL,
            name='Zal buyurtmalari',
        )
        apply_translations(
            hall_distribution,
            'name',
            {'uz': 'Zal buyurtmalari', 'uz_crl': 'Зал буюртмалари', 'ru': 'Заказы из зала'},
        )
        hall_distribution.save()

        takeaway_distribution = DistributionPoint.objects.create(
            restaurant=restaurant,
            kind=DistributionPoint.Kind.TAKEAWAY,
            name='Olib ketish stendi',
        )
        apply_translations(
            takeaway_distribution,
            'name',
            {'uz': 'Olib ketish stendi', 'uz_crl': 'Олиб кетиш стенди', 'ru': 'Стойка навынос'},
        )
        takeaway_distribution.save()

        halls = {}
        hall_zones = {}
        for hall_spec in HALL_SPECS:
            hall = Hall.objects.create(
                restaurant=restaurant,
                name=hall_spec['name']['uz'],
                description=hall_spec['description']['uz'],
                sort_order=hall_spec['sort_order'],
            )
            apply_translations(hall, 'name', hall_spec['name'])
            apply_translations(hall, 'description', hall_spec['description'])
            hall.sort_order = hall_spec['sort_order']
            hall.grid_columns = HALL_GRID_COLUMNS.get(hall_spec['code'], 8)
            hall.save()
            halls[hall_spec['code']] = hall

            hall_zones[hall_spec['code']] = {}
            for zone_index, zone_name in enumerate(ZONE_NAMES, start=1):
                zone = ZoneOrCabin.objects.create(
                    hall=hall,
                    name=zone_name,
                    is_private=False,
                    sort_order=zone_index,
                )
                hall_zones[hall_spec['code']][zone_name] = zone

        business_partner_role = Role.objects.get(code='business_partner')
        restaurant_admin_role = Role.objects.get(code='restaurant_admin')
        owner_role = Role.objects.get(code='owner')
        admin_role = Role.objects.get(code='admin')
        manager_role = Role.objects.get(code='manager')
        waiter_role = Role.objects.get(code='waiter')
        cashier_role = Role.objects.get(code='cashier')
        chef_role = Role.objects.get(code='chef')
        barman_role = Role.objects.get(code='barman')
        universal_operator_role = Role.objects.get(code='universal_operator')
        roles_by_code = {
            'restaurant_admin': restaurant_admin_role,
            'owner': owner_role,
            'admin': admin_role,
            'manager': manager_role,
            'waiter': waiter_role,
            'cashier': cashier_role,
            'chef': chef_role,
            'barman': barman_role,
            'universal_operator': universal_operator_role,
        }
        for tariff_spec in TARIFF_PRESET_SPECS:
            tariff = tariffs_by_key[tariff_spec['key']]
            allowed_roles = [roles_by_code[code] for code in tariff_spec['operational_settings']['enabled_roles']]
            permission_ids = sorted(
                {
                    permission.id
                    for role in allowed_roles
                    for permission in role.permissions.all()
                }
            )
            tariff.permissions.set(permission_ids)
            tariff.allowed_roles.set(allowed_roles)

        entitlement.permissions.set(restaurant_admin_role.permissions.all())
        entitlement_role_codes = dict.fromkeys(
            ['restaurant_admin', *full_service_tariff.operational_settings.get('enabled_roles', [])]
        )
        entitlement.allowed_roles.set([roles_by_code[code] for code in entitlement_role_codes])

        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'full_name': 'System Administrator',
                'ui_mode': User.UiMode.ADMIN,
                'is_staff': True,
                'is_superuser': True,
            },
        )
        admin_user.full_name = 'System Administrator'
        admin_user.role = None
        admin_user.ui_mode = User.UiMode.ADMIN
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password('admin123')
        admin_user.save()

        partner_user, _ = User.objects.get_or_create(
            username='partner_demo',
            defaults={
                'full_name': 'Biznes hamkor demo',
                'role': business_partner_role,
                'ui_mode': User.UiMode.ADMIN,
                'is_staff': True,
            },
        )
        partner_user.full_name = 'Biznes hamkor demo'
        partner_user.role = business_partner_role
        partner_user.ui_mode = User.UiMode.ADMIN
        partner_user.is_staff = True
        partner_user.set_password('partner123')
        partner_user.save()
        BusinessPartnerUserProfile.objects.update_or_create(
            user=partner_user,
            defaults={'business_partner': business_partner},
        )
        business_partner.owner_user = partner_user
        business_partner.save(update_fields=['owner_user'])

        users = [
            ('restaurant_admin', 'Restoran admini', restaurant_admin_role, User.UiMode.ADMIN, 'restadmin123', None),
            ('manager', 'Zal menejeri', manager_role, User.UiMode.ADMIN, 'manager123', None),
            ('waiter', 'Ofitsiant Aziz', waiter_role, User.UiMode.POS, None, '1111'),
            ('waiter2', 'Ofitsiant Sardor', waiter_role, User.UiMode.POS, None, '4444'),
            ('cashier', 'Kassir Madina', cashier_role, User.UiMode.POS, None, '2222'),
            ('chef', 'Oshpaz Bekzod', chef_role, User.UiMode.POS, None, '3333'),
            ('barman', 'Barmen Nodir', barman_role, User.UiMode.POS, None, '5555'),
        ]
        created_users = {}
        for username, full_name, role, ui_mode, password, pin in users:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    'full_name': full_name,
                    'role': role,
                    'ui_mode': ui_mode,
                    'is_staff': ui_mode == User.UiMode.ADMIN,
                },
            )
            user.full_name = full_name
            user.role = role
            user.ui_mode = ui_mode
            user.is_staff = ui_mode == User.UiMode.ADMIN
            if password:
                user.set_password(password)
            if pin:
                user.set_pin(pin)
            else:
                user.pin_code = ''
            user.save()
            user.allowed_halls.set(halls.values())
            profile, _ = RestaurantUserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'restaurant': restaurant,
                    'hall_switch_permission': role in {manager_role, waiter_role, cashier_role},
                    'primary_hall': halls['main-hall'],
                },
            )
            profile.allowed_halls.set(halls.values())
            if pin:
                user.set_pin(pin)
            created_users[username] = user

        for spec in MAIN_HALL_TABLE_SPECS:
            DiningTable.objects.create(
                hall=halls['main-hall'],
                zone=hall_zones['main-hall']['1-qavat'],
                name=f"{halls['main-hall'].name} {spec['table_number']}",
                table_number=spec['table_number'],
                seat_count=spec['seat_count'],
                shape=spec['shape'],
                shape_variant=spec['shape_variant'],
                status=spec['status'],
                position_x=spec['position_x'],
                position_y=spec['position_y'],
                width=spec['width'],
                height=spec['height'],
            )

        for hall_code, table_specs in SECONDARY_HALL_TABLE_SPECS.items():
            hall = halls[hall_code]
            zone_name = '2-qavat' if hall_code.endswith('-l2') else '1-qavat'
            for spec in table_specs:
                DiningTable.objects.create(
                    hall=hall,
                    zone=hall_zones[hall_code][zone_name],
                    name=f"{hall.name} {spec['table_number']}",
                    table_number=spec['table_number'],
                    seat_count=spec['seat_count'],
                    shape=spec['shape'],
                    shape_variant=spec['shape_variant'],
                    status=spec['status'],
                    position_x=spec['position_x'],
                    position_y=spec['position_y'],
                    width=spec['width'],
                    height=spec['height'],
                )

        categories = {}
        for spec in CATEGORY_SPECS:
            category, _ = CatalogCategory.objects.get_or_create(
                restaurant=restaurant,
                mxik_code=spec['mxik_code'],
                defaults={'name': spec['name']['uz'], 'sort_order': spec['sort_order']},
            )
            category.sort_order = spec['sort_order']
            category.mxik_code = spec['mxik_code']
            category.mxik_name = spec['name']['uz']
            apply_translations(category, 'name', spec['name'])
            category.save()
            categories[spec['code']] = category

        items_by_code = {}
        for spec in CATALOG_ITEM_SPECS:
            item, _ = CatalogItem.objects.get_or_create(
                restaurant=restaurant,
                name=spec['name']['uz'],
                defaults={
                    'category': categories[spec['category_code']],
                    'prep_station': prep_stations.get(spec['prep_station_code']),
                    'price': spec['price'],
                },
            )
            item.category = categories[spec['category_code']]
            item.prep_station = prep_stations.get(spec['prep_station_code'])
            item.price = spec['price']
            item.is_active = True
            item.is_stoplisted = False
            apply_translations(item, 'name', spec['name'])
            apply_translations(item, 'description', spec['description'])
            item.save()
            items_by_code[spec['code']] = item

        ensure_mock_configs(restaurant)

        now = timezone.now()
        demo_orders = build_demo_orders(now)
        all_tables = {}
        for hall_code, hall in halls.items():
            for table in DiningTable.objects.filter(hall=hall):
                all_tables[(hall_code, table.table_number)] = table

        for index, spec in enumerate(demo_orders, start=1):
            channel = spec.get('channel', Order.Channel.HALL)
            table = all_tables[(spec['hall_code'], spec['table_no'])] if channel == Order.Channel.HALL else None
            waiter = created_users[spec['waiter']]
            opened_at = spec.get('opened_at')
            if opened_at is None:
                opened_at = now - timedelta(minutes=spec['minutes_ago'])
            is_closed = spec['closed']
            ticket_status = spec.get('ticket_status', KitchenTicket.Status.NEW)
            session_status = spec.get('session_status', TableSession.Status.CLOSED if is_closed else TableSession.Status.OPEN)
            session_closed_at = opened_at + timedelta(minutes=spec.get('close_after_minutes', 42)) if is_closed else None
            if is_closed:
                order_status = Order.Status.CLOSED
            elif channel == Order.Channel.HALL and session_status == TableSession.Status.PENDING_PAYMENT:
                order_status = Order.Status.READY
            elif ticket_status == KitchenTicket.Status.DONE:
                order_status = Order.Status.READY
            else:
                order_status = Order.Status.SUBMITTED

            guest_count = spec.get('guest_count', 2 + (index % 3) if channel == Order.Channel.HALL else 1)
            session = None
            distribution_point = takeaway_distribution if channel == Order.Channel.TAKEAWAY else hall_distribution
            if channel == Order.Channel.HALL:
                session = TableSession.objects.create(
                    restaurant=restaurant,
                    hall=table.hall,
                    table=table,
                    opened_by=waiter,
                    assigned_waiter=waiter,
                    guest_count=guest_count,
                    status=session_status,
                    closed_at=session_closed_at,
                )
                set_model_timestamps(
                    session,
                    created_at=opened_at,
                    updated_at=session_closed_at or opened_at,
                )
                table.status = DiningTable.Status.AVAILABLE if is_closed else DiningTable.Status.OCCUPIED
                table.save(update_fields=['status', 'updated_at'])

            order = Order.objects.create(
                restaurant=restaurant,
                table_session=session,
                distribution_point=distribution_point,
                opened_by=waiter,
                cashier=created_users['cashier'] if is_closed else None,
                order_number=1000 + index,
                channel=channel,
                status=order_status,
                guest_count=guest_count,
                note='',
                closed_at=session_closed_at,
            )

            prep_station_totals = {}
            for item_code in spec['item_codes']:
                catalog_item = items_by_code[item_code]
                price = catalog_item.price
                status = OrderItem.Status.NEW
                if is_closed or ticket_status == KitchenTicket.Status.DONE:
                    status = OrderItem.Status.DONE
                elif ticket_status == KitchenTicket.Status.COOKING:
                    status = OrderItem.Status.COOKING

                order_item = OrderItem.objects.create(
                    order=order,
                    catalog_item=catalog_item,
                    prep_station=catalog_item.prep_station,
                    created_by=waiter,
                    quantity=1,
                    unit_price=price,
                    line_total=price,
                    status=status,
                    note='',
                )
                item_updated_at = session_closed_at or opened_at
                set_model_timestamps(
                    order_item,
                    created_at=opened_at,
                    updated_at=item_updated_at,
                )
                if catalog_item.prep_station_id:
                    prep_station_totals[catalog_item.prep_station_id] = catalog_item.prep_station

            order.recalculate_totals()

            if is_closed:
                payment_time = opened_at + timedelta(minutes=spec.get('payment_delay_minutes', 38))
                payment = Payment.objects.create(
                    order=order,
                    cash_desk=main_cash_desk,
                    received_by=created_users['cashier'],
                    method=Payment.Method.CARD if index % 2 == 0 else Payment.Method.CASH,
                    amount=order.total,
                    status=Payment.Status.SUCCEEDED,
                    external_ref=f'SEED-{order.order_number}',
                    provider_payload={'provider': 'mock-payment'},
                    paid_at=payment_time,
                )
                set_model_timestamps(
                    payment,
                    created_at=payment_time,
                    updated_at=payment_time,
                )
                receipt = Receipt.objects.create(
                    order=order,
                    payment=payment,
                    kind=Receipt.Kind.FISCAL,
                    status=Receipt.Status.SENT,
                    provider='mock-fiscal',
                    payload={'receipt_number': f'RCPT-{order.order_number}'},
                )
                set_model_timestamps(
                    receipt,
                    created_at=payment_time,
                    updated_at=payment_time,
                )
            else:
                for station in prep_station_totals.values():
                    ticket = KitchenTicket.objects.create(
                        restaurant=restaurant,
                                order=order,
                        prep_station=station,
                        status=ticket_status,
                        routed_via=KitchenTicket.RouteMode.BOTH,
                        is_printed=True,
                        printed_payload={'provider': 'mock-printer'},
                    )
                    set_model_timestamps(
                        ticket,
                        created_at=opened_at,
                        updated_at=opened_at,
                    )

            set_model_timestamps(
                order,
                created_at=opened_at,
                updated_at=session_closed_at or opened_at,
            )

        self.stdout.write(self.style.SUCCESS('Demo restaurant bootstrap complete.'))
