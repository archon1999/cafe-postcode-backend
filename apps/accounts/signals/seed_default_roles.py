from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.accounts.models import Permission, PermissionEndpoint, Role


def apply_translations(instance, field_name, translations):
    setattr(instance, field_name, translations['uz'])
    setattr(instance, f'{field_name}_uz', translations['uz'])
    setattr(instance, f'{field_name}_uz_crl', translations['uz_crl'])
    setattr(instance, f'{field_name}_ru', translations['ru'])


def t(uz: str, uz_crl: str | None = None, ru: str | None = None) -> dict[str, str]:
    return {
        'uz': uz,
        'uz_crl': uz_crl or uz,
        'ru': ru or uz,
    }


def endpoint_specs(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [
        {
            'method': method.upper(),
            'url': url,
        }
        for method, url in pairs
    ]


DEFAULT_PERMISSIONS = [
    {'code': 'platform.product_owner.view', 'name': t('Mahsulot egasi platformasiga kirish', 'Маҳсулот эгаси платформасига кириш', 'Доступ к панели владельца продукта')},
    {'code': 'partners.view', 'name': t('Biznes hamkorlarni ko‘rish', 'Бизнес ҳамкорларни кўриш', 'Просмотр бизнес-партнеров')},
    {'code': 'partners.manage', 'name': t('Biznes hamkorlarni boshqarish', 'Бизнес ҳамкорларни бошқариш', 'Управление бизнес-партнерами')},
    {'code': 'partners.activate', 'name': t('Biznes hamkorlarni aktivlashtirish', 'Бизнес ҳамкорларни активлаштириш', 'Активация бизнес-партнеров')},
    {'code': 'partners.deactivate', 'name': t('Biznes hamkorlarni deaktivlashtirish', 'Бизнес ҳамкорларни деактивлаштириш', 'Деактивация бизнес-партнеров')},
    {'code': 'partners.reset_password', 'name': t('Biznes hamkor parolini yangilash', 'Бизнес ҳамкор паролини янгилаш', 'Сброс пароля бизнес-партнера')},
    {'code': 'tariffs.view', 'name': t('Tariflarni ko‘rish', 'Тарифларни кўриш', 'Просмотр тарифов')},
    {'code': 'tariffs.manage', 'name': t('Tariflarni boshqarish', 'Тарифларни бошқариш', 'Управление тарифами')},
    {'code': 'restaurants.view', 'name': t('Restoranlarni ko‘rish', 'Ресторанларни кўриш', 'Просмотр ресторанов')},
    {'code': 'restaurants.manage', 'name': t('Restoranlarni boshqarish', 'Ресторанларни бошқариш', 'Управление ресторанами')},
    {'code': 'restaurants.activate', 'name': t('Restoranlarni aktivlashtirish', 'Ресторанларни активлаштириш', 'Активация ресторанов')},
    {'code': 'restaurants.deactivate', 'name': t('Restoranlarni deaktivlashtirish', 'Ресторанларни деактивлаштириш', 'Деактивация ресторанов')},
    {'code': 'restaurants.reset_password', 'name': t('Restoran admini parolini yangilash', 'Ресторан админи паролини янгилаш', 'Сброс пароля администратора ресторана')},
    {'code': 'dashboard.view', 'name': t('Dashboardni ko‘rish', 'Дашбордни кўриш', 'Просмотр дашборда')},
    {'code': 'constructor.manage', 'name': t('Konstruktorni boshqarish', 'Конструкторни бошқариш', 'Управление конструктором')},
    {'code': 'hall.view', 'name': t('Zallarni ko‘rish', 'Залларни кўриш', 'Просмотр залов')},
    {'code': 'hall.manage', 'name': t('Zallar va joylashuvni boshqarish', 'Заллар ва жойлашувни бошқариш', 'Управление залами и схемой')},
    {'code': 'table.manage', 'name': t('Stollar va sessiyalarni boshqarish', 'Столлар ва сессияларни бошқариш', 'Управление столами и сессиями')},
    {'code': 'users.manage', 'name': t('Xodimlarni boshqarish', 'Ходимларни бошқариш', 'Управление сотрудниками')},
    {'code': 'roles.manage', 'name': t('Rollarni boshqarish', 'Ролларни бошқариш', 'Управление ролями')},
    {'code': 'catalog.view', 'name': t('Menyuni ko‘rish', 'Менюни кўриш', 'Просмотр меню')},
    {'code': 'catalog.manage', 'name': t('Menyuni boshqarish', 'Менюни бошқариш', 'Управление меню')},
    {'code': 'stoplist.manage', 'name': t('Stop-listni boshqarish', 'Стоп-листни бошқариш', 'Управление стоп-листом')},
    {'code': 'orders.create', 'name': t('Buyurtma yaratish', 'Буюртма яратиш', 'Создание заказов')},
    {'code': 'orders.view', 'name': t('Buyurtmalarni ko‘rish', 'Буюртмаларни кўриш', 'Просмотр заказов')},
    {'code': 'orders.manage', 'name': t('Buyurtmalarni boshqarish', 'Буюртмаларни бошқариш', 'Управление заказами')},
    {'code': 'payments.create', 'name': t('To‘lov yaratish', 'Тўлов яратиш', 'Создание платежей')},
    {'code': 'payments.view', 'name': t('To‘lovlarni ko‘rish', 'Тўловларни кўриш', 'Просмотр платежей')},
    {'code': 'payments.manage', 'name': t('To‘lovlarni boshqarish', 'Тўловларни бошқариш', 'Управление платежами')},
    {'code': 'cashdesk.manage', 'name': t('Kassalarni boshqarish', 'Кассаларни бошқариш', 'Управление кассами')},
    {'code': 'cashshift.view', 'name': t('Smenalarni ko‘rish', 'Сменаларни кўриш', 'Просмотр смен')},
    {'code': 'cashshift.open', 'name': t('Smenani ochish', 'Сменани очиш', 'Открытие смены')},
    {'code': 'cashshift.close', 'name': t('Smenani yopish', 'Сменани ёпиш', 'Закрытие смены')},
    {'code': 'payment.refund', 'name': t('To‘lovni qaytarish', 'Тўловни қайтариш', 'Возврат платежа')},
    {'code': 'receipt.reprint', 'name': t('Chekni qayta chop etish', 'Чекни қайта чоп этиш', 'Повторная печать чека')},
    {'code': 'kitchen.view', 'name': t('Oshxona navbatini ko‘rish', 'Ошхона навбатини кўриш', 'Просмотр кухонной очереди')},
    {'code': 'kitchen.update', 'name': t('Oshxona statusini yangilash', 'Ошхона статусини янгилаш', 'Обновление статуса кухни')},
    {'code': 'kitchen.manage', 'name': t('Oshxona jarayonini boshqarish', 'Ошхона жараёнини бошқариш', 'Управление кухонным процессом')},
    {'code': 'reports.view', 'name': t('Hisobotlarni ko‘rish', 'Ҳисоботларни кўриш', 'Просмотр отчетов')},
    {'code': 'reports.shift.view', 'name': t('Smena hisobotlarini ko‘rish', 'Смена ҳисоботларини кўриш', 'Просмотр отчетов по сменам')},
    {'code': 'reports.shift.export', 'name': t('Smena hisobotlarini eksport qilish', 'Смена ҳисоботларини экспорт қилиш', 'Экспорт отчетов по сменам')},
    {'code': 'integrations.manage', 'name': t('Integratsiyalarni boshqarish', 'Интеграцияларни бошқариш', 'Управление интеграциями')},
]


DEFAULT_ROLE_MAP = {
    'product_owner': {
        'name': t('Mahsulot egasi', 'Маҳсулот эгаси', 'Владелец продукта'),
        'permissions': [
            'platform.product_owner.view',
            'partners.view',
            'partners.manage',
            'partners.activate',
            'partners.deactivate',
            'partners.reset_password',
            'tariffs.view',
            'tariffs.manage',
            'restaurants.view',
        ],
    },
    'business_partner': {
        'name': t('Biznes hamkor', 'Бизнес ҳамкор', 'Бизнес-партнер'),
        'permissions': [
            'tariffs.view',
            'restaurants.view',
            'restaurants.manage',
            'restaurants.activate',
            'restaurants.deactivate',
            'restaurants.reset_password',
        ],
    },
    'restaurant_admin': {
        'name': t('Restoran admini', 'Ресторан админи', 'Администратор ресторана'),
        'permissions': [
            'restaurants.manage',
            'hall.view',
            'hall.manage',
            'table.manage',
            'users.manage',
            'catalog.view',
            'catalog.manage',
            'stoplist.manage',
            'orders.view',
            'orders.manage',
            'payments.view',
            'payments.manage',
            'receipt.reprint',
            'kitchen.view',
            'kitchen.update',
            'reports.view',
            'reports.shift.view',
            'reports.shift.export',
            'cashdesk.manage',
            'integrations.manage',
        ],
    },
    'owner': {
        'name': t('Ega', 'Эга', 'Владелец'),
        'permissions': [
            permission['code']
            for permission in DEFAULT_PERMISSIONS
            if not permission['code'].startswith('partners.') and not permission['code'].startswith('tariffs.')
        ],
    },
    'admin': {
        'name': t('Administrator', 'Администратор', 'Администратор'),
        'permissions': [
            'dashboard.view',
            'constructor.manage',
            'hall.view',
            'hall.manage',
            'table.manage',
            'users.manage',
            'catalog.view',
            'catalog.manage',
            'stoplist.manage',
            'cashdesk.manage',
            'payment.refund',
            'reports.view',
            'reports.shift.view',
            'reports.shift.export',
            'integrations.manage',
        ],
    },
    'manager': {
        'name': t('Menejer', 'Менежер', 'Менеджер'),
        'permissions': [
            'dashboard.view',
            'hall.view',
            'hall.manage',
            'table.manage',
            'users.manage',
            'catalog.view',
            'catalog.manage',
            'reports.view',
            'payment.refund',
            'reports.shift.view',
            'reports.shift.export',
        ],
    },
    'cashier': {
        'name': t('Kassir', 'Кассир', 'Кассир'),
        'permissions': [
            'hall.view',
            'catalog.view',
            'orders.create',
            'orders.view',
            'orders.manage',
            'payments.create',
            'payments.view',
            'payments.manage',
            'cashshift.view',
            'cashshift.open',
            'cashshift.close',
            'receipt.reprint',
            'reports.view',
        ],
    },
    'waiter': {
        'name': t('Ofitsiant', 'Официант', 'Официант'),
        'permissions': [
            'hall.view',
            'orders.create',
            'orders.view',
            'orders.manage',
            'table.manage',
        ],
    },
    'chef': {
        'name': t('Oshpaz', 'Ошпаз', 'Повар'),
        'permissions': [
            'kitchen.view',
            'kitchen.update',
            'kitchen.manage',
            'stoplist.manage',
        ],
    },
    'barman': {
        'name': t('Barmen', 'Бармен', 'Бармен'),
        'permissions': [
            'kitchen.view',
            'kitchen.update',
            'kitchen.manage',
            'stoplist.manage',
        ],
    },
    'universal_operator': {
        'name': t('Universal operator', 'Универсал оператор', 'Универсальный оператор'),
        'permissions': [
            'hall.view',
            'catalog.view',
            'orders.create',
            'orders.view',
            'orders.manage',
            'table.manage',
            'payments.create',
            'payments.view',
            'payments.manage',
            'cashshift.view',
            'cashshift.open',
            'cashshift.close',
            'receipt.reprint',
            'kitchen.view',
            'kitchen.update',
            'kitchen.manage',
            'stoplist.manage',
        ],
    },
}


DEFAULT_PERMISSION_ENDPOINTS = {
    'dashboard.view': endpoint_specs(
        ('GET', 'api/v1/dashboard/auth/me/'),
        ('GET', 'api/v1/dashboard/overview/'),
    ),
    'partners.view': endpoint_specs(
        ('GET', 'api/v1/admin/platform/business-partners/'),
        ('GET', 'api/v1/admin/platform/business-partners/<uuid:pk>/'),
    ),
    'partners.manage': endpoint_specs(
        ('POST', 'api/v1/admin/platform/business-partners/'),
        ('PUT', 'api/v1/admin/platform/business-partners/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/platform/business-partners/<uuid:pk>/'),
    ),
    'partners.activate': endpoint_specs(
        ('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/activate/'),
    ),
    'partners.deactivate': endpoint_specs(
        ('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/deactivate/'),
    ),
    'partners.reset_password': endpoint_specs(
        ('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/reset-password/'),
    ),
    'tariffs.view': endpoint_specs(
        ('GET', 'api/v1/admin/users/permissions/'),
        ('GET', 'api/v1/admin/platform/tariffs/'),
        ('GET', 'api/v1/admin/platform/tariffs/<uuid:pk>/'),
    ),
    'tariffs.manage': endpoint_specs(
        ('POST', 'api/v1/admin/platform/tariffs/'),
        ('PUT', 'api/v1/admin/platform/tariffs/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/platform/tariffs/<uuid:pk>/'),
    ),
    'restaurants.view': endpoint_specs(
        ('GET', 'api/v1/admin/constructor/restaurants/'),
        ('GET', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
    ),
    'restaurants.manage': endpoint_specs(
        ('GET', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/'),
        ('POST', 'api/v1/admin/constructor/restaurants/'),
        ('PUT', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/'),
        ('PATCH', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/'),
        ('PUT', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
    ),
    'restaurants.activate': endpoint_specs(
        ('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/activate/'),
    ),
    'restaurants.deactivate': endpoint_specs(
        ('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/deactivate/'),
    ),
    'restaurants.reset_password': endpoint_specs(
        ('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/reset-password/'),
    ),
    'constructor.manage': endpoint_specs(
        ('GET', 'api/v1/admin/constructor/restaurant/'),
        ('PUT', 'api/v1/admin/constructor/restaurant/'),
        ('PATCH', 'api/v1/admin/constructor/restaurant/'),
    ),
    'hall.view': endpoint_specs(
        ('GET', 'api/v1/admin/floor/halls/'),
        ('GET', 'api/v1/admin/floor/halls/<uuid:pk>/'),
        ('GET', 'api/v1/admin/floor/halls/<uuid:pk>/constructor/'),
        ('GET', 'api/v1/admin/floor/zones/'),
        ('GET', 'api/v1/admin/floor/zones/<uuid:pk>/'),
        ('GET', 'api/v1/admin/floor/tables/'),
        ('GET', 'api/v1/admin/floor/tables/<uuid:pk>/'),
        ('GET', 'api/v1/admin/floor/table-sessions/'),
        ('GET', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
        ('GET', 'api/v1/pos/halls/'),
    ),
    'hall.manage': endpoint_specs(
        ('POST', 'api/v1/admin/floor/halls/'),
        ('PUT', 'api/v1/admin/floor/halls/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/floor/halls/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/floor/halls/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/floor/halls/<uuid:pk>/constructor/'),
        ('POST', 'api/v1/admin/floor/zones/'),
        ('PUT', 'api/v1/admin/floor/zones/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/floor/zones/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/floor/zones/<uuid:pk>/'),
    ),
    'table.manage': endpoint_specs(
        ('POST', 'api/v1/admin/floor/tables/'),
        ('PUT', 'api/v1/admin/floor/tables/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/floor/tables/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/floor/tables/<uuid:pk>/'),
        ('POST', 'api/v1/admin/floor/table-sessions/'),
        ('PUT', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
        ('GET', 'api/v1/pos/halls/table-sessions/'),
        ('POST', 'api/v1/pos/halls/table-sessions/'),
        ('GET', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
        ('PUT', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
        ('PATCH', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
        ('POST', 'api/v1/pos/halls/table-sessions/<uuid:pk>/move/'),
        ('POST', 'api/v1/pos/halls/table-sessions/<uuid:pk>/merge/'),
    ),
    'users.manage': endpoint_specs(
        ('GET', 'api/v1/admin/users/roles/'),
        ('POST', 'api/v1/admin/users/roles/'),
        ('GET', 'api/v1/admin/users/roles/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/users/roles/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/users/roles/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/users/roles/<uuid:pk>/'),
        ('GET', 'api/v1/admin/users/'),
        ('POST', 'api/v1/admin/users/'),
        ('GET', 'api/v1/admin/users/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/users/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/users/<uuid:pk>/'),
    ),
    'catalog.view': endpoint_specs(
        ('GET', 'api/v1/pos/catalog/menu/'),
    ),
    'catalog.manage': endpoint_specs(
        ('GET', 'api/v1/admin/catalog/categories/'),
        ('POST', 'api/v1/admin/catalog/categories/'),
        ('GET', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
        ('GET', 'api/v1/admin/catalog/items/'),
        ('POST', 'api/v1/admin/catalog/items/'),
        ('GET', 'api/v1/admin/catalog/items/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/catalog/items/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/catalog/items/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/catalog/items/<uuid:pk>/'),
        ('POST', 'api/v1/admin/catalog/items/<uuid:pk>/stoplist/'),
        ('GET', 'api/v1/admin/catalog/mxik/search/'),
        ('GET', 'api/v1/admin/catalog/mxik/<str:code>/'),
    ),
    'stoplist.manage': [],
    'orders.create': [],
    'orders.view': endpoint_specs(
        ('GET', 'api/v1/admin/orders/'),
        ('GET', 'api/v1/admin/orders/<uuid:pk>/'),
        ('GET', 'api/v1/admin/order-items/'),
        ('GET', 'api/v1/admin/order-items/<uuid:pk>/'),
        ('GET', 'api/v1/admin/order-item-notes/'),
        ('GET', 'api/v1/admin/order-item-notes/<uuid:pk>/'),
        ('GET', 'api/v1/pos/orders/<uuid:pk>/'),
        ('PUT', 'api/v1/pos/orders/<uuid:pk>/'),
        ('PATCH', 'api/v1/pos/orders/<uuid:pk>/'),
    ),
    'orders.manage': endpoint_specs(
        ('GET', 'api/v1/pos/orders/'),
        ('POST', 'api/v1/pos/orders/'),
        ('GET', 'api/v1/pos/orders/<uuid:order_id>/items/'),
        ('POST', 'api/v1/pos/orders/<uuid:order_id>/items/'),
        ('GET', 'api/v1/pos/orders/items/<uuid:pk>/'),
        ('PUT', 'api/v1/pos/orders/items/<uuid:pk>/'),
        ('PATCH', 'api/v1/pos/orders/items/<uuid:pk>/'),
        ('DELETE', 'api/v1/pos/orders/items/<uuid:pk>/'),
        ('POST', 'api/v1/pos/orders/<uuid:pk>/submit/'),
    ),
    'payments.create': [],
    'payments.view': endpoint_specs(
        ('GET', 'api/v1/admin/payments/'),
        ('GET', 'api/v1/admin/payments/<uuid:pk>/'),
        ('GET', 'api/v1/admin/receipts/'),
        ('GET', 'api/v1/admin/receipts/<uuid:pk>/'),
    ),
    'payments.manage': endpoint_specs(
        ('GET', 'api/v1/pos/payments/open-checks/'),
        ('POST', 'api/v1/pos/payments/orders/<uuid:pk>/pay/'),
    ),
    'cashdesk.manage': endpoint_specs(
        ('GET', 'api/v1/admin/constructor/cash-desks/'),
        ('POST', 'api/v1/admin/constructor/cash-desks/'),
        ('GET', 'api/v1/admin/constructor/cash-desks/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/constructor/cash-desks/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/constructor/cash-desks/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/constructor/cash-desks/<uuid:pk>/'),
    ),
    'cashshift.view': endpoint_specs(
        ('GET', 'api/v1/pos/cashier/context/'),
    ),
    'cashshift.open': endpoint_specs(
        ('POST', 'api/v1/pos/cashier/shifts/open/'),
    ),
    'cashshift.close': endpoint_specs(
        ('POST', 'api/v1/pos/cashier/shifts/current/close/'),
    ),
    'payment.refund': endpoint_specs(
        ('POST', 'api/v1/pos/payments/<uuid:pk>/refund/'),
    ),
    'receipt.reprint': endpoint_specs(
        ('POST', 'api/v1/pos/receipts/<uuid:pk>/reprint/'),
    ),
    'kitchen.view': endpoint_specs(
        ('GET', 'api/v1/admin/kitchen/tickets/'),
        ('GET', 'api/v1/admin/kitchen/tickets/<uuid:pk>/'),
        ('GET', 'api/v1/pos/kitchen/queue/'),
        ('GET', 'api/v1/pos/kitchen/tickets/<uuid:pk>/'),
    ),
    'kitchen.update': [],
    'kitchen.manage': endpoint_specs(
        ('POST', 'api/v1/pos/kitchen/tickets/<uuid:pk>/status/'),
        ('POST', 'api/v1/pos/kitchen/items/<uuid:pk>/status/'),
    ),
    'reports.view': endpoint_specs(
        ('GET', 'api/v1/admin/reports/summary/'),
        ('GET', 'api/v1/admin/reports/summary/export/'),
        ('GET', 'api/v1/admin/reports/sales/'),
        ('GET', 'api/v1/admin/reports/sales/export/'),
        ('GET', 'api/v1/admin/reports/open-checks/'),
        ('GET', 'api/v1/admin/reports/open-checks/export/'),
        ('GET', 'api/v1/admin/reports/top-items/'),
        ('GET', 'api/v1/admin/reports/top-items/export/'),
        ('GET', 'api/v1/admin/reports/top-staff/'),
        ('GET', 'api/v1/admin/reports/top-staff/export/'),
        ('GET', 'api/v1/admin/reports/payment-breakdown/'),
        ('GET', 'api/v1/admin/reports/payment-breakdown/export/'),
        ('GET', 'api/v1/reports/summary/'),
        ('GET', 'api/v1/reports/sales/'),
        ('GET', 'api/v1/reports/sales/export/'),
        ('GET', 'api/v1/reports/open-checks/'),
        ('GET', 'api/v1/reports/top-items/'),
        ('GET', 'api/v1/reports/top-staff/'),
        ('GET', 'api/v1/reports/payment-breakdown/'),
    ),
    'reports.shift.view': endpoint_specs(
        ('GET', 'api/v1/admin/reports/shifts/'),
    ),
    'reports.shift.export': endpoint_specs(
        ('GET', 'api/v1/admin/reports/shifts/export/'),
    ),
    'integrations.manage': endpoint_specs(
        ('GET', 'api/v1/admin/constructor/prep-stations/'),
        ('POST', 'api/v1/admin/constructor/prep-stations/'),
        ('GET', 'api/v1/admin/constructor/prep-stations/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/constructor/prep-stations/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/constructor/prep-stations/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/constructor/prep-stations/<uuid:pk>/'),
        ('GET', 'api/v1/admin/constructor/devices/'),
        ('POST', 'api/v1/admin/constructor/devices/'),
        ('GET', 'api/v1/admin/constructor/devices/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/constructor/devices/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/constructor/devices/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/constructor/devices/<uuid:pk>/'),
        ('GET', 'api/v1/admin/constructor/distribution-points/'),
        ('POST', 'api/v1/admin/constructor/distribution-points/'),
        ('GET', 'api/v1/admin/constructor/distribution-points/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/constructor/distribution-points/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/constructor/distribution-points/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/constructor/distribution-points/<uuid:pk>/'),
        ('GET', 'api/v1/admin/integrations/configs/'),
        ('POST', 'api/v1/admin/integrations/configs/'),
        ('GET', 'api/v1/admin/integrations/configs/<uuid:pk>/'),
        ('PUT', 'api/v1/admin/integrations/configs/<uuid:pk>/'),
        ('PATCH', 'api/v1/admin/integrations/configs/<uuid:pk>/'),
        ('DELETE', 'api/v1/admin/integrations/configs/<uuid:pk>/'),
    ),
}


@receiver(post_migrate)
def seed_default_roles_signal(sender, **kwargs):
    if sender.label != 'accounts':
        return

    permissions_by_code = {}
    for permission_data in DEFAULT_PERMISSIONS:
        code = permission_data['code']
        translated_name = permission_data['name']
        permission, _ = Permission.objects.get_or_create(code=code, defaults={'name': translated_name['uz']})
        apply_translations(permission, 'name', translated_name)
        apply_translations(permission, 'description', translated_name)
        permission.save()
        desired_endpoints = {
            (endpoint['method'], endpoint['url'])
            for endpoint in DEFAULT_PERMISSION_ENDPOINTS.get(code, [])
        }
        for method, url in desired_endpoints:
            PermissionEndpoint.objects.update_or_create(
                url=url,
                method=method,
                defaults={'permission': permission},
            )

        for endpoint in permission.endpoints.all():
            if (endpoint.method, endpoint.url) not in desired_endpoints:
                endpoint.delete()
        permissions_by_code[code] = permission

    for code, role_data in DEFAULT_ROLE_MAP.items():
        role, _ = Role.objects.get_or_create(
            code=code,
            defaults={'name': role_data['name']['uz'], 'description': role_data['name']['uz']},
        )
        apply_translations(role, 'name', role_data['name'])
        apply_translations(role, 'description', role_data['name'])
        role.is_system = True
        role.save()
        role.permissions.set([permissions_by_code[item] for item in role_data['permissions']])
