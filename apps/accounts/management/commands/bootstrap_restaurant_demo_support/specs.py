from dataclasses import dataclass, field

from apps.orders.models import Order


@dataclass(frozen=True)
class TariffSpec:
    key: str
    name: str
    description: str
    role_codes: tuple[str, ...]
    monthly_price: int
    yearly_price: int


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
    service_fee_percent: int = 0


@dataclass(frozen=True)
class StaffSpec:
    username: str
    full_name: str
    role_code: str
    ui_mode: str
    password: str | None = None
    pin: str | None = None
    primary_hall_code: str | None = None
    allowed_hall_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderSpec:
    number: int
    channel: str
    item_codes: tuple[str, ...]
    opened_by: str
    cashier: str | None = None
    hall_code: str | None = None
    table_number: int | None = None
    guest_count: int = 1
    closed: bool = False
    note: str = ''


TARIFF_SPECS = (
    TariffSpec(
        key='restaurant',
        name='Restaurant tarifi',
        description='Zallar, restoran boshqaruvi, oshxona va POS oqimlari bilan to‘liq restoran tarifi.',
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

RESTAURANT_SPECS = (
    RestaurantSpec(
        key='restaurant',
        name='Postcode Restaurant',
        legal_name='Postcode Restaurant MCHJ',
        tax_number='200100300',
        phone='+998901112233',
        address='Toshkent shahri, Yunusobod tumani',
        tariff_key='restaurant',
        hall_enabled=True,
        kitchen_enabled=True,
        cashier_enabled=True,
        owner_dashboard_enabled=True,
        order_entry_mode='hall',
        kitchen_mode='both',
        service_fee_percent=10,
    ),
    RestaurantSpec(
        key='fast_food',
        name='Postcode Fast Food',
        legal_name='Postcode Fast Food MCHJ',
        tax_number='200100301',
        phone='+998901112244',
        address='Toshkent shahri, Chilonzor tumani',
        tariff_key='fast_food',
        hall_enabled=False,
        kitchen_enabled=True,
        cashier_enabled=True,
        owner_dashboard_enabled=True,
        order_entry_mode='cashier_builder',
        kitchen_mode='display',
        service_fee_percent=0,
    ),
)

RESTAURANT_STAFF_SPECS = (
    StaffSpec('restaurant-owner', 'Restaurant mahsulot egasi', 'owner', 'admin', 'owner123'),
    StaffSpec('restaurant-manager', 'Restaurant menejer', 'manager', 'pos', pin='1101', primary_hall_code='main', allowed_hall_codes=('main', 'family')),
    StaffSpec('restaurant-waiter', 'Restaurant ofitsiant', 'waiter', 'pos', pin='1102', primary_hall_code='main', allowed_hall_codes=('main', 'family')),
    StaffSpec('restaurant-cashier', 'Restaurant kassir', 'cashier', 'pos', pin='1103'),
    StaffSpec('restaurant-chef', 'Restaurant oshpaz', 'chef', 'pos', pin='1104'),
    StaffSpec('restaurant-barman', 'Restaurant barmen', 'barman', 'pos', pin='1105'),
)

FAST_FOOD_STAFF_SPECS = (
    StaffSpec('fastfood-owner', 'Fast food mahsulot egasi', 'owner', 'admin', 'owner123'),
    StaffSpec('fastfood-manager', 'Fast food menejer', 'fast_food_manager', 'pos', pin='2201'),
    StaffSpec('fastfood-cashier', 'Fast food kassir', 'fast_food_cashier', 'pos', pin='2202'),
    StaffSpec('fastfood-chef', 'Fast food oshpaz', 'chef', 'pos', pin='2203'),
)

HALL_SPECS = (
    {'code': 'main', 'name': 'Asosiy zal', 'description': 'Asosiy mehmonlar zali', 'sort_order': 1},
    {'code': 'family', 'name': 'Oilaviy zal', 'description': 'Oilaviy stol zonasi', 'sort_order': 2},
)

TABLE_SPECS = {
    'main': (
        {'table_number': 1, 'name': 'A1', 'seat_count': 4, 'position_x': 1, 'position_y': 1},
        {'table_number': 2, 'name': 'A2', 'seat_count': 4, 'position_x': 3, 'position_y': 1},
    ),
    'family': (
        {'table_number': 1, 'name': 'F1', 'seat_count': 6, 'position_x': 1, 'position_y': 1},
    ),
}

CATALOG_SPECS = {
    'restaurant': (
        {
            'category_name': 'Milliy taomlar',
            'category_code': '01006001002000000',
            'category_mxik_name': 'Необработанный рис',
            'image_url': 'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/01006001002000000_1.png',
            'items': (
                {
                    'code': 'restaurant-rice',
                    'name': 'Sholi garnir',
                    'mxik_code': '01006001002000000',
                    'mxik_name': 'Необработанный рис',
                    'price': 18000,
                    'prep_station_code': 'kitchen',
                },
                {
                    'code': 'restaurant-liver',
                    'name': 'Jigar say',
                    'mxik_code': '00206001002000000',
                    'mxik_name': 'Печень',
                    'price': 39000,
                    'prep_station_code': 'kitchen',
                },
                {
                    'code': 'restaurant-beans',
                    'name': 'Loviya salati',
                    'mxik_code': '00708002001000000',
                    'mxik_name': 'Бобы',
                    'price': 22000,
                    'prep_station_code': 'kitchen',
                },
            ),
        },
        {
            'category_name': 'Ichimliklar',
            'category_code': '02206002002000000',
            'category_mxik_name': 'Квас',
            'image_url': 'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/02206002002000000_1.png',
            'items': (
                {
                    'code': 'restaurant-kvass',
                    'name': 'Kvass',
                    'mxik_code': '02206002002000000',
                    'mxik_name': 'Квас',
                    'price': 14000,
                    'prep_station_code': None,
                },
                {
                    'code': 'restaurant-cocoa',
                    'name': 'Kakao',
                    'mxik_code': '01806002001000000',
                    'mxik_name': 'Какао',
                    'price': 16000,
                    'prep_station_code': 'bar',
                },
            ),
        },
    ),
    'fast_food': (
        {
            'category_name': 'Fast food garnirlari',
            'category_code': '00701001001000000',
            'category_mxik_name': 'Картошка',
            'image_url': 'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/00701001001000000_1.png',
            'items': (
                {
                    'code': 'fastfood-fries',
                    'name': 'Fries box',
                    'mxik_code': '00701001001000000',
                    'mxik_name': 'Картошка',
                    'price': 17000,
                    'prep_station_code': 'kitchen',
                },
                {
                    'code': 'fastfood-sauce',
                    'name': 'Burger sauce',
                    'mxik_code': '02103001004000000',
                    'mxik_name': 'Соус',
                    'price': 8000,
                    'prep_station_code': None,
                },
            ),
        },
        {
            'category_name': 'Sovuq ichimliklar',
            'category_code': '02202002006000000',
            'category_mxik_name': 'Морс',
            'image_url': 'https://tasnif.soliq.uz/api/cls-api/integration-mxik/references/get/file/02202002006000000_1.png',
            'items': (
                {
                    'code': 'fastfood-mors',
                    'name': 'Berry mors',
                    'mxik_code': '02202002006000000',
                    'mxik_name': 'Морс',
                    'price': 15000,
                    'prep_station_code': None,
                },
                {
                    'code': 'fastfood-cocoa',
                    'name': 'Kakao shake',
                    'mxik_code': '01806002001000000',
                    'mxik_name': 'Какао',
                    'price': 20000,
                    'prep_station_code': None,
                },
            ),
        },
    ),
}

RESTAURANT_ORDER_SPECS = (
    OrderSpec(
        number=1001,
        channel=Order.Channel.HALL,
        item_codes=('restaurant-rice', 'restaurant-kvass'),
        opened_by='restaurant-waiter',
        cashier='restaurant-cashier',
        hall_code='main',
        table_number=1,
        guest_count=2,
        closed=True,
    ),
    OrderSpec(
        number=1002,
        channel=Order.Channel.HALL,
        item_codes=('restaurant-liver', 'restaurant-cocoa'),
        opened_by='restaurant-waiter',
        hall_code='family',
        table_number=1,
        guest_count=4,
        closed=False,
    ),
)

FAST_FOOD_ORDER_SPECS = (
    OrderSpec(
        number=2001,
        channel=Order.Channel.TAKEAWAY,
        item_codes=('fastfood-fries', 'fastfood-mors'),
        opened_by='fastfood-cashier',
        cashier='fastfood-cashier',
        closed=True,
        note='Takeaway order',
    ),
    OrderSpec(
        number=2002,
        channel=Order.Channel.TAKEAWAY,
        item_codes=('fastfood-fries', 'fastfood-sauce', 'fastfood-cocoa'),
        opened_by='fastfood-manager',
        closed=False,
        note='Takeaway queue',
    ),
)

TOP_LEVEL_USERS = {
    'superadmin': {'username': 'admin', 'password': 'admin123', 'full_name': 'System Administrator'},
    'product_owner': {'username': 'padmin', 'password': 'padmin123', 'full_name': 'Platforma mahsulot egasi'},
}

BUSINESS_PARTNER_SPEC = {
    'inn': '309876543',
    'company_name': 'Postcode hamkor',
    'legal_name': 'Postcode hamkor MCHJ',
    'director_name': 'Demo Director',
    'phone': '+998901234567',
    'email': 'partner.demo@postcode.uz',
    'address': 'Toshkent shahri, Shayxontohur tumani',
}

PREP_STATION_SPECS = {
    'restaurant': (
        {'code': 'kitchen', 'name': 'Asosiy oshxona', 'kind': 'kitchen'},
        {'code': 'bar', 'name': 'Bar', 'kind': 'bar'},
    ),
    'fast_food': (
        {'code': 'kitchen', 'name': 'Fast food oshxona', 'kind': 'kitchen'},
    ),
}

DISTRIBUTION_POINT_SPECS = {
    'restaurant': (
        {'name': 'Zal buyurtmalari', 'kind': 'hall'},
        {'name': 'Olib ketish', 'kind': 'takeaway'},
    ),
    'fast_food': (
        {'name': 'Takeaway', 'kind': 'takeaway'},
    ),
}

CASH_DESK_SPECS = {
    'restaurant': ('Asosiy kassa', 'Kirish qismi'),
    'fast_food': ('Fast food kassa', 'Front desk'),
}

DEVICE_SPECS = {
    'restaurant': (
        {'name': 'Waiter Tablet', 'mode': 'waiter'},
        {'name': 'Cashier POS', 'mode': 'cashier'},
        {'name': 'Kitchen Display', 'mode': 'kitchen_display'},
    ),
    'fast_food': (
        {'name': 'Fast Food POS', 'mode': 'cashier'},
        {'name': 'Fast Food Kitchen', 'mode': 'kitchen_display'},
    ),
}

MODULES_BY_TARIFF = {
    'restaurant': ['hall', 'kitchen', 'cashier', 'owner_dashboard'],
    'fast_food': ['kitchen', 'cashier', 'owner_dashboard'],
}

STAFF_SPECS_BY_RESTAURANT = {
    'restaurant': RESTAURANT_STAFF_SPECS,
    'fast_food': FAST_FOOD_STAFF_SPECS,
}

ORDER_SPECS_BY_RESTAURANT = {
    'restaurant': RESTAURANT_ORDER_SPECS,
    'fast_food': FAST_FOOD_ORDER_SPECS,
}
