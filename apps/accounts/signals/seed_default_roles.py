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
    {'code': 'platform.product_owner.view', 'name': t('Platform access', 'Платформага кириш', 'Доступ к платформе')},
    {'code': 'partners.view', 'name': t('View business partners', 'Бизнес ҳамкорларни кўриш', 'Просмотр бизнес-партнеров')},
    {'code': 'partners.manage', 'name': t('Manage business partners', 'Бизнес ҳамкорларни бошқариш', 'Управление бизнес-партнерами')},
    {'code': 'partners.activate', 'name': t('Activate business partners', 'Бизнес ҳамкорни активлаштириш', 'Активация бизнес-партнеров')},
    {'code': 'partners.deactivate', 'name': t('Deactivate business partners', 'Бизнес ҳамкорни деактивлаштириш', 'Деактивация бизнес-партнеров')},
    {'code': 'partners.reset_password', 'name': t('Reset partner password', 'Ҳамкор паролини янгилаш', 'Сброс пароля партнера')},
    {'code': 'tariffs.view', 'name': t('View tariffs', 'Тарифларни кўриш', 'Просмотр тарифов')},
    {'code': 'tariffs.manage', 'name': t('Manage tariffs', 'Тарифларни бошқариш', 'Управление тарифами')},
    {'code': 'restaurants.view', 'name': t('View restaurants', 'Ресторанларни кўриш', 'Просмотр ресторанов')},
    {'code': 'restaurants.manage', 'name': t('Manage restaurants', 'Ресторанларни бошқариш', 'Управление ресторанами')},
    {'code': 'restaurants.activate', 'name': t('Activate restaurants', 'Ресторанни активлаштириш', 'Активация ресторанов')},
    {'code': 'restaurants.deactivate', 'name': t('Deactivate restaurants', 'Ресторанни деактивлаштириш', 'Деактивация ресторанов')},
    {'code': 'restaurants.reset_password', 'name': t('Reset restaurant admin password', 'Ресторан админи паролини янгилаш', 'Сброс пароля администратора ресторана')},
    {'code': 'dashboard.view', 'name': t('View dashboard', 'Дашбордни кўриш', 'Просмотр дашборда')},
    {'code': 'constructor.manage', 'name': t('Manage constructor', 'Конструкторни бошқариш', 'Управление конструктором')},
    {'code': 'hall.view', 'name': t('View halls', 'Залларни кўриш', 'Просмотр залов')},
    {'code': 'hall.manage', 'name': t('Manage halls and layout', 'Зал ва жойлашувни бошқариш', 'Управление залом и схемой')},
    {'code': 'table.manage', 'name': t('Manage tables and sessions', 'Стол ва сессияларни бошқариш', 'Управление столами и сессиями')},
    {'code': 'users.manage', 'name': t('Manage employees', 'Ходимларни бошқариш', 'Управление сотрудниками')},
    {'code': 'roles.manage', 'name': t('Manage roles', 'Ролларни бошқариш', 'Управление ролями')},
    {'code': 'catalog.view', 'name': t('View menu', 'Менюни кўриш', 'Просмотр меню')},
    {'code': 'catalog.manage', 'name': t('Manage menu', 'Менюни бошқариш', 'Управление меню')},
    {'code': 'stoplist.manage', 'name': t('Manage stop list', 'Стоп-листни бошқариш', 'Управление стоп-листом')},
    {'code': 'orders.create', 'name': t('Create orders', 'Буюртма яратиш', 'Создание заказов')},
    {'code': 'orders.view', 'name': t('View orders', 'Буюртмаларни кўриш', 'Просмотр заказов')},
    {'code': 'orders.manage', 'name': t('Manage orders', 'Буюртмаларни бошқариш', 'Управление заказами')},
    {'code': 'payments.create', 'name': t('Create payments', 'Тўлов яратиш', 'Создание платежей')},
    {'code': 'payments.view', 'name': t('View payments', 'Тўловларни кўриш', 'Просмотр платежей')},
    {'code': 'payments.manage', 'name': t('Manage payments', 'Тўловларни бошқариш', 'Управление платежами')},
    {'code': 'cashdesk.manage', 'name': t('Manage cash desks', 'Кассаларни бошқариш', 'Управление кассами')},
    {'code': 'cashshift.view', 'name': t('View shifts', 'Сменаларни кўриш', 'Просмотр смен')},
    {'code': 'cashshift.open', 'name': t('Open shift', 'Смена очиш', 'Открытие смены')},
    {'code': 'cashshift.close', 'name': t('Close shift', 'Смена ёпиш', 'Закрытие смены')},
    {'code': 'payment.refund', 'name': t('Refund payment', 'Тўловни қайтариш', 'Возврат платежа')},
    {'code': 'receipt.reprint', 'name': t('Reprint receipt', 'Чекни қайта чоп этиш', 'Повторная печать чека')},
    {'code': 'kitchen.view', 'name': t('View kitchen queue', 'Ошхона навбатини кўриш', 'Просмотр кухонной очереди')},
    {'code': 'kitchen.update', 'name': t('Update kitchen status', 'Ошхона статусини янгилаш', 'Обновление статуса кухни')},
    {'code': 'kitchen.manage', 'name': t('Manage kitchen process', 'Ошхона жараёнини бошқариш', 'Управление кухонным процессом')},
    {'code': 'reports.view', 'name': t('View reports', 'Ҳисоботларни кўриш', 'Просмотр отчетов')},
    {'code': 'reports.shift.view', 'name': t('View shift reports', 'Смена ҳисоботларини кўриш', 'Просмотр отчетов по сменам')},
    {'code': 'reports.shift.export', 'name': t('Export shift reports', 'Смена ҳисоботларини экспорт қилиш', 'Экспорт отчетов по сменам')},
    {'code': 'integrations.manage', 'name': t('Manage integrations', 'Интеграцияларни бошқариш', 'Управление интеграциями')},
]


DEFAULT_ROLE_MAP = {
    'product_owner': {
        'name': t('Product owner', 'Маҳсулот эгаси', 'Владелец продукта'),
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
        'name': t('Business partner', 'Бизнес ҳамкор', 'Бизнес-партнер'),
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
        'name': t('Restaurant admin', 'Ресторан админи', 'Администратор ресторана'),
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
        'name': t('Owner', 'Эга', 'Владелец'),
        'permissions': [permission['code'] for permission in DEFAULT_PERMISSIONS if not permission['code'].startswith('partners.') and not permission['code'].startswith('tariffs.')],
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
        'name': t('Manager', 'Менежер', 'Менеджер'),
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
        'name': t('Cashier', 'Кассир', 'Кассир'),
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
        'name': t('Waiter', 'Официант', 'Официант'),
        'permissions': [
            'hall.view',
            'orders.create',
            'orders.view',
            'orders.manage',
            'table.manage',
        ],
    },
    'chef': {
        'name': t('Chef', 'Ошпаз', 'Повар'),
        'permissions': [
            'kitchen.view',
            'kitchen.update',
            'kitchen.manage',
            'stoplist.manage',
        ],
    },
    'barman': {
        'name': t('Barman', 'Бармен', 'Бармен'),
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
