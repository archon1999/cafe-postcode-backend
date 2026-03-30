from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.accounts.models import Permission, Role


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
