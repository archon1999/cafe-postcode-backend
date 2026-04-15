from dataclasses import dataclass

from apps.billing.models import Payment
from apps.floor.models import DiningTable
from apps.sales.models import Order


def mxik_image_url(mxik_code: str) -> str:
    return f'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/{mxik_code}_1.png'


@dataclass(frozen=True)
class TariffSpec:
    key: str
    name: str
    description: str
    role_codes: tuple[str, ...]
    monthly_price: int
    yearly_price: int


@dataclass(frozen=True)
class StaffSpec:
    username: str
    full_name: str
    role_code: str
    surface: str
    password: str | None = None
    pin: str | None = None
    primary_hall_code: str | None = None
    allowed_hall_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ZoneSpec:
    code: str
    name: str
    sort_order: int


@dataclass(frozen=True)
class TableSpec:
    table_number: int
    name: str
    seat_count: int
    position_x: int
    position_y: int
    width: int = 1
    height: int = 1
    status: str = DiningTable.Status.AVAILABLE


@dataclass(frozen=True)
class HallSpec:
    code: str
    zone_code: str
    name: str
    description: str
    sort_order: int
    tables: tuple[TableSpec, ...]


@dataclass(frozen=True)
class FloorSpec:
    zones: tuple[ZoneSpec, ...]
    halls: tuple[HallSpec, ...]


@dataclass(frozen=True)
class PrepStationSpec:
    code: str
    name: str
    kind: str


@dataclass(frozen=True)
class DistributionPointSpec:
    name: str
    kind: str
    assigned_hall_code: str | None = None


@dataclass(frozen=True)
class SetupSpec:
    prep_stations: tuple[PrepStationSpec, ...]
    distribution_points: tuple[DistributionPointSpec, ...]
    cash_desk_name: str
    cash_desk_location: str


@dataclass(frozen=True)
class CatalogItemSpec:
    code: str
    name: str
    mxik_code: str
    mxik_name: str
    price: int
    prep_station_code: str | None = None
    description: str = ''


@dataclass(frozen=True)
class CatalogCategorySpec:
    category_name: str
    category_code: str
    category_mxik_name: str
    image_url: str
    items: tuple[CatalogItemSpec, ...]


@dataclass(frozen=True)
class HistoryProfileSpec:
    base_order_number: int
    weekday_closed_orders: int
    weekend_closed_orders: int
    today_closed_orders: int
    today_active_orders: int
    closed_channel_cycle: tuple[str, ...]
    active_channel_cycle: tuple[str, ...]
    payment_method_cycle: tuple[str, ...]
    opener_usernames: tuple[str, ...]
    cashier_usernames: tuple[str, ...]
    active_status_cycle: tuple[str, ...]
    active_hall_table_keys: tuple[tuple[str, int], ...] = ()
    item_count_cycle: tuple[int, ...] = (2, 3, 4, 3)


@dataclass(frozen=True)
class RestaurantSpec:
    key: str
    name: str
    legal_name: str
    tax_number: str
    phone: str
    address: str
    tariff_key: str
    hall_enabled: bool
    kitchen_enabled: bool
    cashier_enabled: bool
    owner_dashboard_enabled: bool
    order_entry_mode: str
    kitchen_mode: str
    floor: FloorSpec | None
    catalog: tuple[CatalogCategorySpec, ...]
    staff: tuple[StaffSpec, ...]
    setup: SetupSpec
    history: HistoryProfileSpec
    service_fee_percent: int = 0


def item(
    *,
    code: str,
    name: str,
    mxik_code: str,
    mxik_name: str,
    price: int,
    prep_station_code: str | None = None,
    description: str = '',
) -> CatalogItemSpec:
    return CatalogItemSpec(
        code=code,
        name=name,
        mxik_code=mxik_code,
        mxik_name=mxik_name,
        price=price,
        prep_station_code=prep_station_code,
        description=description or name,
    )


def category(
    *,
    name: str,
    mxik_code: str,
    mxik_name: str,
    items: tuple[CatalogItemSpec, ...],
) -> CatalogCategorySpec:
    return CatalogCategorySpec(
        category_name=name,
        category_code=mxik_code,
        category_mxik_name=mxik_name,
        image_url=mxik_image_url(mxik_code),
        items=items,
    )


TARIFF_SPECS = (
    TariffSpec(
        key='restaurant',
        name='Restaurant tarifi',
        description='Zallar, restoran boshqaruvi, oshxona va POS oqimlari bilan toliq restoran tarifi.',
        role_codes=('owner', 'restaurant_admin', 'manager', 'cashier', 'waiter', 'chef', 'barman'),
        monthly_price=990000,
        yearly_price=9900000,
    ),
    TariffSpec(
        key='fast_food',
        name='Fast food tarifi',
        description='Zalsiz, olib ketish va tezkor kassaga mos fast food tarifi.',
        role_codes=('owner', 'fast_food_admin', 'fast_food_manager', 'fast_food_cashier', 'chef'),
        monthly_price=590000,
        yearly_price=5900000,
    ),
)


RESTAURANT_FLOOR_SPEC = FloorSpec(
    zones=(
        ZoneSpec(code='main_zone', name='Asosiy zona', sort_order=1),
        ZoneSpec(code='terrace_zone', name='Ayvon zona', sort_order=2),
        ZoneSpec(code='vip_zone', name='VIP zona', sort_order=3),
    ),
    halls=(
        HallSpec(
            code='main',
            zone_code='main_zone',
            name='Asosiy zal',
            description='Kunlik mehmonlar uchun asosiy zal',
            sort_order=1,
            tables=(
                TableSpec(table_number=1, name='A1', seat_count=4, position_x=1, position_y=1),
                TableSpec(table_number=2, name='A2', seat_count=4, position_x=3, position_y=1),
                TableSpec(table_number=3, name='A3', seat_count=6, position_x=5, position_y=1),
                TableSpec(table_number=4, name='A4', seat_count=4, position_x=2, position_y=3),
                TableSpec(table_number=5, name='A5', seat_count=6, position_x=5, position_y=3),
            ),
        ),
        HallSpec(
            code='family',
            zone_code='main_zone',
            name='Oilaviy zal',
            description='Oilaviy buyurtmalar uchun sokin zona',
            sort_order=2,
            tables=(
                TableSpec(table_number=1, name='F1', seat_count=6, position_x=1, position_y=1),
                TableSpec(table_number=2, name='F2', seat_count=6, position_x=4, position_y=1),
                TableSpec(table_number=3, name='F3', seat_count=4, position_x=2, position_y=3),
                TableSpec(table_number=4, name='F4', seat_count=4, position_x=5, position_y=3),
            ),
        ),
        HallSpec(
            code='terrace',
            zone_code='terrace_zone',
            name='Yozgi ayvon',
            description='Ochiq havo maydoni',
            sort_order=3,
            tables=(
                TableSpec(table_number=1, name='T1', seat_count=4, position_x=1, position_y=1),
                TableSpec(table_number=2, name='T2', seat_count=4, position_x=3, position_y=1),
                TableSpec(table_number=3, name='T3', seat_count=4, position_x=5, position_y=1),
                TableSpec(table_number=4, name='T4', seat_count=6, position_x=2, position_y=3, status=DiningTable.Status.RESERVED),
            ),
        ),
        HallSpec(
            code='vip_1',
            zone_code='vip_zone',
            name='VIP 1',
            description='Yopiq uchrashuvlar xonasi',
            sort_order=4,
            tables=(
                TableSpec(table_number=1, name='V1-1', seat_count=6, position_x=1, position_y=1),
                TableSpec(table_number=2, name='V1-2', seat_count=6, position_x=4, position_y=1),
            ),
        ),
        HallSpec(
            code='vip_2',
            zone_code='vip_zone',
            name='VIP 2',
            description='Maxsus buyurtmalar uchun xususiy xona',
            sort_order=5,
            tables=(
                TableSpec(table_number=1, name='V2-1', seat_count=4, position_x=1, position_y=1),
                TableSpec(table_number=2, name='V2-2', seat_count=4, position_x=3, position_y=1),
                TableSpec(table_number=3, name='V2-3', seat_count=6, position_x=5, position_y=1, status=DiningTable.Status.BLOCKED),
            ),
        ),
    ),
)


RESTAURANT_STAFF_SPECS = (
    StaffSpec('restaurant-owner', 'Restaurant mahsulot egasi', 'owner', 'admin', password='owner123'),
    StaffSpec(
        'restaurant-manager',
        'Restaurant menejer',
        'manager',
        'pos',
        pin='1111',
        primary_hall_code='main',
        allowed_hall_codes=('main', 'family', 'terrace', 'vip_1', 'vip_2'),
    ),
    StaffSpec(
        'restaurant-waiter-1',
        'Restaurant ofitsiant 1',
        'waiter',
        'pos',
        pin='2221',
        primary_hall_code='main',
        allowed_hall_codes=('main', 'family', 'terrace'),
    ),
    StaffSpec(
        'restaurant-waiter-2',
        'Restaurant ofitsiant 2',
        'waiter',
        'pos',
        pin='2222',
        primary_hall_code='family',
        allowed_hall_codes=('family', 'vip_1', 'vip_2'),
    ),
    StaffSpec('restaurant-cashier-1', 'Restaurant kassir 1', 'cashier', 'pos', pin='3331'),
    StaffSpec('restaurant-cashier-2', 'Restaurant kassir 2', 'cashier', 'pos', pin='3332'),
    StaffSpec('restaurant-chef-1', 'Restaurant oshpaz 1', 'chef', 'pos', pin='4441'),
    StaffSpec('restaurant-chef-2', 'Restaurant oshpaz 2', 'chef', 'pos', pin='4442'),
    StaffSpec('restaurant-barman', 'Restaurant barmen', 'barman', 'pos', pin='5551'),
)


FAST_FOOD_STAFF_SPECS = (
    StaffSpec('fastfood-owner', 'Fast food mahsulot egasi', 'owner', 'admin', password='owner123'),
    StaffSpec('fastfood-manager', 'Fast food menejer', 'fast_food_manager', 'pos', pin='6111'),
    StaffSpec('fastfood-cashier-1', 'Fast food kassir 1', 'fast_food_cashier', 'pos', pin='6221'),
    StaffSpec('fastfood-cashier-2', 'Fast food kassir 2', 'fast_food_cashier', 'pos', pin='6222'),
    StaffSpec('fastfood-chef-1', 'Fast food oshpaz 1', 'chef', 'pos', pin='6331'),
    StaffSpec('fastfood-chef-2', 'Fast food oshpaz 2', 'chef', 'pos', pin='6332'),
)


RESTAURANT_SETUP_SPEC = SetupSpec(
    prep_stations=(
        PrepStationSpec(code='hot_kitchen', name='Issiq oshxona', kind='kitchen'),
        PrepStationSpec(code='grill', name='Grill stansiyasi', kind='kitchen'),
        PrepStationSpec(code='salad', name='Salat stansiyasi', kind='other'),
        PrepStationSpec(code='bar', name='Bar', kind='bar'),
    ),
    distribution_points=(
        DistributionPointSpec(name='Zal buyurtmalari', kind='hall', assigned_hall_code='main'),
        DistributionPointSpec(name='Olib ketish', kind='takeaway'),
        DistributionPointSpec(name='Yetkazib berish', kind='delivery'),
        DistributionPointSpec(name='Online vitrina', kind='online'),
    ),
    cash_desk_name='Asosiy kassa',
    cash_desk_location='Kirish qismi',
)


FAST_FOOD_SETUP_SPEC = SetupSpec(
    prep_stations=(
        PrepStationSpec(code='kitchen', name='Fast food oshxona', kind='kitchen'),
        PrepStationSpec(code='fryer', name='Fryer stansiyasi', kind='other'),
        PrepStationSpec(code='beverage', name='Ichimlik stansiyasi', kind='bar'),
    ),
    distribution_points=(
        DistributionPointSpec(name='Takeaway', kind='takeaway'),
        DistributionPointSpec(name='Delivery', kind='delivery'),
        DistributionPointSpec(name='Online queue', kind='online'),
    ),
    cash_desk_name='Fast food kassa',
    cash_desk_location='Front desk',
)


RESTAURANT_CATALOG_SPECS = (
    category(
        name='Milliy taomlar',
        mxik_code='01006001002000000',
        mxik_name='Neobrabotanniy ris',
        items=(
            item(code='restaurant-choyxona-ris', name='Choyxona guruchi', mxik_code='01006001002000000', mxik_name='Neobrabotanniy ris', price=26000, prep_station_code='hot_kitchen'),
            item(code='restaurant-saralangan-ris', name='Saralangan guruch', mxik_code='01006001001000000', mxik_name='Ris razvesnoy', price=28000, prep_station_code='hot_kitchen'),
            item(code='restaurant-sutli-guruch', name='Sutli guruch', mxik_code='00401001001000000', mxik_name='Moloko', price=24000, prep_station_code='hot_kitchen'),
            item(code='restaurant-quyultirilgan-guruch', name='Quyultirilgan sutli guruch', mxik_code='00402001001000000', mxik_name='Moloko sgushchennoe', price=32000, prep_station_code='hot_kitchen'),
        ),
    ),
    category(
        name='Kaboblar',
        mxik_code='00206001002000000',
        mxik_name='Pechen',
        items=(
            item(code='restaurant-til-kabobi', name='Til kabobi', mxik_code='00206001001000000', mxik_name='Yazyk', price=52000, prep_station_code='grill'),
            item(code='restaurant-jigar-say', name='Jigar say', mxik_code='00206001002000000', mxik_name='Pechen', price=46000, prep_station_code='grill'),
            item(code='restaurant-dum-qovurdoq', name='Dum qovurdoq', mxik_code='00206001004000000', mxik_name='Hvost', price=48000, prep_station_code='grill'),
            item(code='restaurant-golyashka-tandir', name='Golyashka tandir', mxik_code='00206001005000000', mxik_name='Golyashka', price=59000, prep_station_code='grill'),
            item(code='restaurant-yurak-kabobi', name='Yurak kabobi', mxik_code='00206001006000000', mxik_name='Serdtse', price=43000, prep_station_code='grill'),
        ),
    ),
    category(
        name='Shorvalar',
        mxik_code='00401001001000000',
        mxik_name='Moloko',
        items=(
            item(code='restaurant-sutli-shorva', name='Sutli shorva', mxik_code='00401001001000000', mxik_name='Moloko', price=22000, prep_station_code='hot_kitchen'),
            item(code='restaurant-yogurt-okroshka', name='Yogurt okroshka', mxik_code='00403002001000000', mxik_name='Yogurt', price=24000, prep_station_code='hot_kitchen'),
            item(code='restaurant-kefir-shorva', name='Kefirli shorva', mxik_code='00403003001000000', mxik_name='Kefir', price=23000, prep_station_code='hot_kitchen'),
            item(code='restaurant-syuzmali-shorva', name='Syuzmali shorva', mxik_code='00403004001000000', mxik_name='Syuzma', price=26000, prep_station_code='hot_kitchen'),
        ),
    ),
    category(
        name='Salatlar',
        mxik_code='00709001906000000',
        mxik_name='Salat listovoy',
        items=(
            item(code='restaurant-loviya-salati', name='Loviya salati', mxik_code='00708002001000000', mxik_name='Boby', price=24000, prep_station_code='salad'),
            item(code='restaurant-dzhando-salati', name='Dzhando salati', mxik_code='00708002002000000', mxik_name='Struchkovaya fasol', price=26000, prep_station_code='salad'),
            item(code='restaurant-fasol-salati', name='Fasol salati', mxik_code='00708002003000000', mxik_name='Fasol', price=25000, prep_station_code='salad'),
            item(code='restaurant-bargli-salat', name='Bargli salat', mxik_code='00709001906000000', mxik_name='Salat listovoy', price=21000, prep_station_code='salad'),
            item(code='restaurant-timyanli-kokat', name='Timyanli kokat', mxik_code='00709001909000000', mxik_name='Timyan', price=23000, prep_station_code='salad'),
        ),
    ),
    category(
        name='Nonushta',
        mxik_code='00403002001000000',
        mxik_name='Yogurt',
        items=(
            item(code='restaurant-yogurt-bowl', name='Yogurt bowl', mxik_code='00403002001000000', mxik_name='Yogurt', price=29000, prep_station_code='hot_kitchen'),
            item(code='restaurant-kefir-bowl', name='Kefir bowl', mxik_code='00403003001000000', mxik_name='Kefir', price=27000, prep_station_code='hot_kitchen'),
            item(code='restaurant-banan-breakfast', name='Bananli breakfast', mxik_code='00803001001000000', mxik_name='Banan svezhie', price=31000, prep_station_code='hot_kitchen'),
            item(code='restaurant-golubika-breakfast', name='Golubikali breakfast', mxik_code='00810999009000000', mxik_name='Golubika', price=34000, prep_station_code='hot_kitchen'),
            item(code='restaurant-yongoq-breakfast', name='Grek yongoqli breakfast', mxik_code='00801001001000000', mxik_name='Oreh gretskiy', price=36000, prep_station_code='hot_kitchen'),
        ),
    ),
    category(
        name='Shirinliklar',
        mxik_code='00804007001000000',
        mxik_name='Mango',
        items=(
            item(code='restaurant-mango-desert', name='Mango desert', mxik_code='00804007001000000', mxik_name='Mango', price=33000, prep_station_code='bar'),
            item(code='restaurant-hurma-desert', name='Hurmali desert', mxik_code='00810999018000000', mxik_name='Hurma', price=31000, prep_station_code='bar'),
            item(code='restaurant-kokos-krem', name='Kokosli krem', mxik_code='00801007001000000', mxik_name='Kokos', price=32000, prep_station_code='bar'),
            item(code='restaurant-kakao-muss', name='Kakao muss', mxik_code='01806002001000000', mxik_name='Kakao', price=29000, prep_station_code='bar'),
            item(code='restaurant-issiq-shokolad', name='Issiq shokolad lava', mxik_code='01806002003000000', mxik_name='Goryachiy shokolad', price=34000, prep_station_code='bar'),
        ),
    ),
    category(
        name='Ichimliklar',
        mxik_code='02202002006000000',
        mxik_name='Mors',
        items=(
            item(code='restaurant-limonad', name='Limonad', mxik_code='00805002001000000', mxik_name='Limon', price=18000, prep_station_code='bar'),
            item(code='restaurant-house-soda', name='House soda', mxik_code='02202002001000000', mxik_name='Bezalkogolnye napitki', price=19000, prep_station_code='bar'),
            item(code='restaurant-juice-drink', name='Juice drink', mxik_code='02202002005000000', mxik_name='Sokosoderzhashchie napitki', price=21000, prep_station_code='bar'),
            item(code='restaurant-berry-mors', name='Berry mors', mxik_code='02202002006000000', mxik_name='Mors', price=22000, prep_station_code='bar'),
            item(code='restaurant-energy-mix', name='Energy mix', mxik_code='02202003001000000', mxik_name='Energeticheskiy napitok', price=25000, prep_station_code='bar'),
            item(code='restaurant-kvass', name='Kvass', mxik_code='02206002002000000', mxik_name='Kvass', price=17000, prep_station_code='bar'),
            item(code='restaurant-kakao-ichimlik', name='Kakao', mxik_code='01806002002000000', mxik_name='Kakao napitok rastvorimiy', price=23000, prep_station_code='bar'),
        ),
    ),
)
FAST_FOOD_CATALOG_SPECS = (
    category(
        name='Burgerlar',
        mxik_code='02102001001000000',
        mxik_name='Drozhzhi',
        items=(
            item(code='fastfood-classic-burger', name='Classic burger', mxik_code='02102001001000000', mxik_name='Drozhzhi', price=34000, prep_station_code='kitchen'),
            item(code='fastfood-double-burger', name='Double burger', mxik_code='02102001001000000', mxik_name='Drozhzhi', price=43000, prep_station_code='kitchen'),
            item(code='fastfood-cheese-burger', name='Cheese burger', mxik_code='02102002001000000', mxik_name='Razryhlitel', price=39000, prep_station_code='kitchen'),
            item(code='fastfood-spicy-burger', name='Spicy burger', mxik_code='02102002001000000', mxik_name='Razryhlitel', price=40000, prep_station_code='kitchen'),
        ),
    ),
    category(
        name='Lavash va doner',
        mxik_code='00709001906000000',
        mxik_name='Salat listovoy',
        items=(
            item(code='fastfood-chicken-lavash', name='Chicken lavash', mxik_code='02102001001000000', mxik_name='Drozhzhi', price=36000, prep_station_code='kitchen'),
            item(code='fastfood-beef-doner', name='Beef doner', mxik_code='02102001001000000', mxik_name='Drozhzhi', price=38000, prep_station_code='kitchen'),
            item(code='fastfood-fresh-wrap', name='Fresh wrap', mxik_code='00709001906000000', mxik_name='Salat listovoy', price=29000, prep_station_code='kitchen'),
            item(code='fastfood-bean-wrap', name='Bean wrap', mxik_code='00708002003000000', mxik_name='Fasol', price=31000, prep_station_code='kitchen'),
        ),
    ),
    category(
        name='Fried sides',
        mxik_code='00701001001000000',
        mxik_name='Kartoshka',
        items=(
            item(code='fastfood-fries-box', name='Fries box', mxik_code='00701001001000000', mxik_name='Kartoshka', price=18000, prep_station_code='fryer'),
            item(code='fastfood-rustic-potato', name='Rustic potato', mxik_code='00701001001000000', mxik_name='Kartoshka', price=21000, prep_station_code='fryer'),
            item(code='fastfood-potato-wedges', name='Potato wedges', mxik_code='00701001001000000', mxik_name='Kartoshka', price=22000, prep_station_code='fryer'),
            item(code='fastfood-bean-crisps', name='Bean crisps', mxik_code='00708002002000000', mxik_name='Struchkovaya fasol', price=17000, prep_station_code='fryer'),
        ),
    ),
    category(
        name='Combo',
        mxik_code='02202002001000000',
        mxik_name='Bezalkogolnye napitki',
        items=(
            item(code='fastfood-burger-combo', name='Burger combo', mxik_code='02202002001000000', mxik_name='Bezalkogolnye napitki', price=47000),
            item(code='fastfood-family-combo', name='Family combo', mxik_code='02202002005000000', mxik_name='Sokosoderzhashchie napitki', price=62000),
            item(code='fastfood-lunch-combo', name='Lunch combo', mxik_code='02202002006000000', mxik_name='Mors', price=52000),
        ),
    ),
    category(
        name='Issiq ichimliklar',
        mxik_code='01806002001000000',
        mxik_name='Kakao',
        items=(
            item(code='fastfood-kakao-shake', name='Kakao shake', mxik_code='01806002001000000', mxik_name='Kakao', price=22000, prep_station_code='beverage'),
            item(code='fastfood-instant-cocoa', name='Instant cocoa', mxik_code='01806002002000000', mxik_name='Kakao napitok rastvorimiy', price=20000, prep_station_code='beverage'),
            item(code='fastfood-hot-chocolate', name='Hot chocolate', mxik_code='01806002003000000', mxik_name='Goryachiy shokolad', price=24000, prep_station_code='beverage'),
        ),
    ),
    category(
        name='Sovuq ichimliklar',
        mxik_code='02202002006000000',
        mxik_name='Mors',
        items=(
            item(code='fastfood-cola-style', name='Cola style', mxik_code='02202002001000000', mxik_name='Bezalkogolnye napitki', price=15000, prep_station_code='beverage'),
            item(code='fastfood-juice-cup', name='Juice cup', mxik_code='02202002005000000', mxik_name='Sokosoderzhashchie napitki', price=17000, prep_station_code='beverage'),
            item(code='fastfood-mors-cup', name='Mors cup', mxik_code='02202002006000000', mxik_name='Mors', price=18000, prep_station_code='beverage'),
            item(code='fastfood-energy-can', name='Energy can', mxik_code='02202003001000000', mxik_name='Energeticheskiy napitok', price=23000, prep_station_code='beverage'),
            item(code='fastfood-kvass-cup', name='Kvass cup', mxik_code='02206002002000000', mxik_name='Kvass', price=16000, prep_station_code='beverage'),
        ),
    ),
    category(
        name='Souslar',
        mxik_code='02103001004000000',
        mxik_name='Sous',
        items=(
            item(code='fastfood-house-sauce', name='House sauce', mxik_code='02103001004000000', mxik_name='Sous', price=9000),
            item(code='fastfood-garlic-sauce', name='Garlic sauce', mxik_code='02103001004000000', mxik_name='Sous', price=9000),
            item(code='fastfood-cheese-sauce', name='Cheese sauce', mxik_code='02103001004000000', mxik_name='Sous', price=10000),
            item(code='fastfood-bbq-sauce', name='BBQ sauce', mxik_code='02103001004000000', mxik_name='Sous', price=10000),
            item(code='fastfood-chili-sauce', name='Chili sauce', mxik_code='02103001004000000', mxik_name='Sous', price=10000),
        ),
    ),
)


RESTAURANT_HISTORY_PROFILE = HistoryProfileSpec(
    base_order_number=1000,
    weekday_closed_orders=3,
    weekend_closed_orders=5,
    today_closed_orders=3,
    today_active_orders=3,
    closed_channel_cycle=(Order.Channel.HALL, Order.Channel.HALL, Order.Channel.HALL, Order.Channel.TAKEAWAY, Order.Channel.DELIVERY, Order.Channel.ONLINE),
    active_channel_cycle=(Order.Channel.HALL, Order.Channel.HALL, Order.Channel.DELIVERY),
    payment_method_cycle=(Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR, Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR),
    opener_usernames=('restaurant-waiter-1', 'restaurant-waiter-2', 'restaurant-manager', 'restaurant-cashier-1', 'restaurant-manager'),
    cashier_usernames=('restaurant-cashier-1', 'restaurant-cashier-2'),
    active_status_cycle=(Order.Status.SUBMITTED, Order.Status.READY, Order.Status.SUBMITTED),
    active_hall_table_keys=(('main', 1), ('family', 1)),
)


FAST_FOOD_HISTORY_PROFILE = HistoryProfileSpec(
    base_order_number=4000,
    weekday_closed_orders=2,
    weekend_closed_orders=3,
    today_closed_orders=4,
    today_active_orders=2,
    closed_channel_cycle=(Order.Channel.TAKEAWAY, Order.Channel.TAKEAWAY, Order.Channel.DELIVERY, Order.Channel.ONLINE),
    active_channel_cycle=(Order.Channel.TAKEAWAY, Order.Channel.DELIVERY),
    payment_method_cycle=(Payment.Method.CASH, Payment.Method.CARD, Payment.Method.QR, Payment.Method.CASH, Payment.Method.CARD),
    opener_usernames=('fastfood-cashier-1', 'fastfood-cashier-2', 'fastfood-manager'),
    cashier_usernames=('fastfood-cashier-1', 'fastfood-cashier-2'),
    active_status_cycle=(Order.Status.SUBMITTED, Order.Status.READY),
)


RESTAURANT_SPECS = (
    RestaurantSpec(
        key='restaurant',
        name='GULISTON RESTAURANT',
        legal_name='GULISTON RESTAURANT MCHJ',
        tax_number='311926992',
        phone='+998337700586',
        address="Buxoro viloyati, Buxoro shahri, Gulchorbog' MFY, Gazli shoh ko'chasi, 291-uy",
        tariff_key='restaurant',
        hall_enabled=True,
        kitchen_enabled=True,
        cashier_enabled=True,
        owner_dashboard_enabled=True,
        order_entry_mode='hall',
        kitchen_mode='both',
        floor=RESTAURANT_FLOOR_SPEC,
        catalog=RESTAURANT_CATALOG_SPECS,
        staff=RESTAURANT_STAFF_SPECS,
        setup=RESTAURANT_SETUP_SPEC,
        history=RESTAURANT_HISTORY_PROFILE,
        service_fee_percent=10,
    ),
    RestaurantSpec(
        key='fast_food',
        name='BROCCOLI FOOD',
        legal_name='BROCCOLI FOOD MCHJ',
        tax_number='304459113',
        phone='+998909112881',
        address="Toshkent shahri, Mirobod tumani, Fidokor ko'chasi, 7-uy",
        tariff_key='fast_food',
        hall_enabled=False,
        kitchen_enabled=True,
        cashier_enabled=True,
        owner_dashboard_enabled=True,
        order_entry_mode='cashier_builder',
        kitchen_mode='display',
        floor=None,
        catalog=FAST_FOOD_CATALOG_SPECS,
        staff=FAST_FOOD_STAFF_SPECS,
        setup=FAST_FOOD_SETUP_SPEC,
        history=FAST_FOOD_HISTORY_PROFILE,
        service_fee_percent=0,
    ),
)


TOP_LEVEL_USERS = {
    'superadmin': {'username': 'superadmin', 'password': 'superadmin123', 'full_name': 'System Administrator'},
    'product_owner': {'username': 'admin', 'password': 'admin123', 'full_name': 'Platforma mahsulot egasi'},
}


BUSINESS_PARTNER_SPEC = {
    'inn': '310162774',
    'company_name': 'ABSOLYUT POWER SYSTEM MCHJ',
    'legal_name': 'ABSOLYUT POWER SYSTEM MCHJ',
    'director_name': 'Jurayev Akmaljon Ruzibayevich',
    'phone': '+998983381004',
    'email': 'info@absolyutpower.uz',
    'address': "Toshkent viloyati, Chirchiq shahri, Umid mahallasi, V. Qodirov ko'chasi, 1-V uy",
}
