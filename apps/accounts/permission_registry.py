from collections import defaultdict


def t(uz: str, uz_crl: str | None = None, ru: str | None = None) -> dict[str, str]:
    return {
        'uz': uz,
        'uz_crl': uz_crl or uz,
        'ru': ru or uz,
    }


def endpoint_specs(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{'method': method.upper(), 'url': url} for method, url in pairs]


ROLE_DEFINITIONS = {
    'product_owner': {'name': t('Mahsulot egasi')},
    'business_partner': {'name': t('Biznes hamkor')},
    'restaurant_admin': {'name': t('Restoran admini')},
    'owner': {'name': t('Ega')},
    'admin': {'name': t('Administrator')},
    'manager': {'name': t('Menejer')},
    'cashier': {'name': t('Kassir')},
    'waiter': {'name': t('Ofitsiant')},
    'chef': {'name': t('Oshpaz')},
    'barman': {'name': t('Barmen')},
    'universal_operator': {'name': t('Universal operator')},
}

PRODUCT_OWNER_ROLES = ('product_owner',)
PARTNER_ROLES = ('product_owner', 'business_partner')
ROLE_MANAGEMENT_ROLES = ('product_owner', 'owner', 'restaurant_admin')
RESTAURANT_OWNER_ROLES = ('owner', 'restaurant_admin')
EMPLOYEE_MANAGEMENT_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager')
RESTAURANT_ADMIN_UI_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager')
RESTAURANT_SETUP_ROLES = ('owner', 'restaurant_admin', 'admin')
FLOOR_OPERATIONS_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager', 'cashier', 'waiter', 'universal_operator')
ORDER_VIEW_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager', 'cashier', 'waiter', 'universal_operator')
ORDER_WRITE_ROLES = ('owner', 'restaurant_admin', 'cashier', 'waiter', 'universal_operator')
PAYMENT_ADMIN_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager')
PAYMENT_OPERATION_ROLES = ('owner', 'restaurant_admin', 'cashier', 'universal_operator')
KITCHEN_VIEW_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager', 'chef', 'barman', 'universal_operator')
KITCHEN_OPERATION_ROLES = ('owner', 'restaurant_admin', 'chef', 'barman', 'universal_operator')
REPORTING_ROLES = ('owner', 'restaurant_admin', 'admin', 'manager')
WAITER_ROLES = ('owner', 'restaurant_admin', 'waiter', 'universal_operator')
CASHIER_ROLES = ('owner', 'restaurant_admin', 'cashier', 'universal_operator')


def permission_definition(
    code: str,
    *,
    surface: str,
    resource: str,
    action: str,
    ui_visible: bool,
    group_key: str,
    name: str,
    endpoints: list[dict[str, str]] | None = None,
    default_roles: tuple[str, ...] = (),
    description: str | None = None,
) -> dict:
    return {
        'code': code,
        'surface': surface,
        'resource': resource,
        'action': action,
        'ui_visible': ui_visible,
        'group_key': group_key,
        'name': t(name),
        'description': t(description or name),
        'endpoints': endpoints or [],
        'default_roles': list(default_roles),
    }


def crud_permissions(
    code_prefix: str,
    *,
    surface: str,
    group_key: str,
    singular_label: str,
    plural_label: str,
    list_url: str,
    detail_url: str,
    default_roles: tuple[str, ...],
    list_endpoints: list[dict[str, str]] | None = None,
    view_endpoints: list[dict[str, str]] | None = None,
    create_endpoints: list[dict[str, str]] | None = None,
    update_endpoints: list[dict[str, str]] | None = None,
    delete_endpoints: list[dict[str, str]] | None = None,
    include_create: bool = True,
    include_update: bool = True,
    include_delete: bool = True,
    list_surface: str | None = None,
    view_surface: str | None = None,
    create_surface: str | None = None,
    update_surface: str | None = None,
    delete_surface: str | None = None,
    list_default_roles: tuple[str, ...] | None = None,
    view_default_roles: tuple[str, ...] | None = None,
    create_default_roles: tuple[str, ...] | None = None,
    update_default_roles: tuple[str, ...] | None = None,
    delete_default_roles: tuple[str, ...] | None = None,
) -> list[dict]:
    items = [
        permission_definition(
            f'{code_prefix}.list',
            surface=list_surface or surface,
            resource=code_prefix,
            action='list',
            ui_visible=True,
            group_key=group_key,
            name=f'{plural_label} ro‘yxatini ko‘rish',
            endpoints=list_endpoints or endpoint_specs(('GET', list_url)),
            default_roles=list_default_roles or default_roles,
        ),
        permission_definition(
            f'{code_prefix}.view',
            surface=view_surface or surface,
            resource=code_prefix,
            action='view',
            ui_visible=True,
            group_key=group_key,
            name=f'{singular_label}ni ko‘rish',
            endpoints=view_endpoints or endpoint_specs(('GET', detail_url)),
            default_roles=view_default_roles or default_roles,
        ),
    ]
    if include_create:
        items.append(
            permission_definition(
                f'{code_prefix}.create',
                surface=create_surface or surface,
                resource=code_prefix,
                action='create',
                ui_visible=True,
                group_key=group_key,
                name=f'{singular_label} yaratish',
                endpoints=create_endpoints or endpoint_specs(('POST', list_url)),
                default_roles=create_default_roles or default_roles,
            )
        )
    if include_update:
        items.append(
            permission_definition(
                f'{code_prefix}.update',
                surface=update_surface or surface,
                resource=code_prefix,
                action='update',
                ui_visible=True,
                group_key=group_key,
                name=f'{singular_label}ni tahrirlash',
                endpoints=update_endpoints or endpoint_specs(('PUT', detail_url), ('PATCH', detail_url)),
                default_roles=update_default_roles or default_roles,
            )
        )
    if include_delete:
        items.append(
            permission_definition(
                f'{code_prefix}.delete',
                surface=delete_surface or surface,
                resource=code_prefix,
                action='delete',
                ui_visible=True,
                group_key=group_key,
                name=f'{singular_label}ni o‘chirish',
                endpoints=delete_endpoints or endpoint_specs(('DELETE', detail_url)),
                default_roles=delete_default_roles or default_roles,
            )
        )
    return items


def action_permission(
    code: str,
    *,
    surface: str,
    group_key: str,
    name: str,
    endpoints: list[dict[str, str]],
    default_roles: tuple[str, ...],
    ui_visible: bool = True,
) -> dict:
    resource, action = code.rsplit('.', 1)
    return permission_definition(
        code,
        surface=surface,
        resource=resource,
        action=action,
        ui_visible=ui_visible,
        group_key=group_key,
        name=name,
        endpoints=endpoints,
        default_roles=default_roles,
    )


PERMISSION_DEFINITIONS = [
    permission_definition(
        'platform.product_owner.view',
        surface='admin',
        resource='platform.product_owner',
        action='view',
        ui_visible=False,
        group_key='platform',
        name='Mahsulot egasi paneliga kirish',
        default_roles=PRODUCT_OWNER_ROLES,
    ),
    permission_definition(
        'dashboard.view',
        surface='dashboard',
        resource='dashboard',
        action='view',
        ui_visible=True,
        group_key='dashboard',
        name='Dashboardni ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/dashboard/auth/me/'), ('GET', 'api/v1/dashboard/overview/')),
        default_roles=('owner', 'restaurant_admin', 'admin', 'manager'),
    ),
    permission_definition(
        'permissions.list',
        surface='admin',
        resource='permissions',
        action='list',
        ui_visible=True,
        group_key='permissions',
        name='Ruxsatlar katalogini ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/admin/users/permissions/')),
        default_roles=ROLE_MANAGEMENT_ROLES,
    ),
    permission_definition(
        'restaurant_settings.view',
        surface='admin',
        resource='restaurant_settings',
        action='view',
        ui_visible=True,
        group_key='restaurant_settings',
        name='Restoran sozlamalarini ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/admin/constructor/restaurant/')),
        default_roles=('owner', 'restaurant_admin', 'admin'),
    ),
    permission_definition(
        'restaurant_settings.update',
        surface='admin',
        resource='restaurant_settings',
        action='update',
        ui_visible=True,
        group_key='restaurant_settings',
        name='Restoran sozlamalarini tahrirlash',
        endpoints=endpoint_specs(('PUT', 'api/v1/admin/constructor/restaurant/'), ('PATCH', 'api/v1/admin/constructor/restaurant/')),
        default_roles=('owner', 'restaurant_admin', 'admin'),
    ),
    permission_definition(
        'restaurant_feature_configs.view',
        surface='admin',
        resource='restaurant_feature_configs',
        action='view',
        ui_visible=True,
        group_key='restaurant_feature_configs',
        name='Funksiya sozlamalarini ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/')),
        default_roles=RESTAURANT_OWNER_ROLES,
    ),
    permission_definition(
        'restaurant_feature_configs.update',
        surface='admin',
        resource='restaurant_feature_configs',
        action='update',
        ui_visible=True,
        group_key='restaurant_feature_configs',
        name='Funksiya sozlamalarini tahrirlash',
        endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/'),
            ('PATCH', 'api/v1/admin/restaurants/<uuid:restaurant_id>/feature-config/'),
        ),
        default_roles=RESTAURANT_OWNER_ROLES,
    ),
    permission_definition(
        'catalog_menu.view',
        surface='pos',
        resource='catalog_menu',
        action='view',
        ui_visible=True,
        group_key='catalog',
        name='POS menyusini ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/pos/catalog/menu/')),
        default_roles=('owner', 'restaurant_admin', 'cashier', 'waiter', 'universal_operator'),
    ),
    permission_definition(
        'open_checks.list',
        surface='pos',
        resource='open_checks',
        action='list',
        ui_visible=True,
        group_key='payments',
        name='Ochiq cheklar ro‘yxatini ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/payments/open-checks/'),
            ('GET', 'api/v1/pos/cashier/context/'),
        ),
        default_roles=CASHIER_ROLES,
    ),
    permission_definition(
        'payments.create',
        surface='pos',
        resource='payments',
        action='create',
        ui_visible=True,
        group_key='payments',
        name='To‘lov qabul qilish',
        endpoints=endpoint_specs(('POST', 'api/v1/pos/payments/orders/<uuid:pk>/pay/')),
        default_roles=CASHIER_ROLES,
    ),
    permission_definition(
        'payments.update',
        surface='pos',
        resource='payments',
        action='update',
        ui_visible=True,
        group_key='payments',
        name='To‘lov amallarini bajarish',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/cashier/shifts/open/'),
            ('POST', 'api/v1/pos/cashier/shifts/current/close/'),
            ('POST', 'api/v1/pos/payments/<uuid:pk>/refund/'),
            ('POST', 'api/v1/pos/receipts/<uuid:pk>/reprint/'),
        ),
        default_roles=PAYMENT_OPERATION_ROLES,
    ),
    permission_definition(
        'kitchen_queue.view',
        surface='pos',
        resource='kitchen_queue',
        action='view',
        ui_visible=True,
        group_key='kitchen',
        name='Oshxona navbatini ko‘rish',
        endpoints=endpoint_specs(('GET', 'api/v1/pos/kitchen/queue/')),
        default_roles=KITCHEN_OPERATION_ROLES,
    ),
    permission_definition(
        'reports.view',
        surface='admin',
        resource='reports',
        action='view',
        ui_visible=True,
        group_key='reports',
        name='Hisobotlarni ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/reports/summary/'),
            ('GET', 'api/v1/reports/summary/'),
            ('GET', 'api/v1/admin/reports/summary/export/'),
            ('GET', 'api/v1/admin/reports/sales/'),
            ('GET', 'api/v1/reports/sales/'),
            ('GET', 'api/v1/admin/reports/sales/export/'),
            ('GET', 'api/v1/reports/sales/export/'),
            ('GET', 'api/v1/admin/reports/open-checks/'),
            ('GET', 'api/v1/reports/open-checks/'),
            ('GET', 'api/v1/admin/reports/open-checks/export/'),
            ('GET', 'api/v1/admin/reports/top-items/'),
            ('GET', 'api/v1/reports/top-items/'),
            ('GET', 'api/v1/admin/reports/top-items/export/'),
            ('GET', 'api/v1/admin/reports/top-staff/'),
            ('GET', 'api/v1/reports/top-staff/'),
            ('GET', 'api/v1/admin/reports/top-staff/export/'),
            ('GET', 'api/v1/admin/reports/payment-breakdown/'),
            ('GET', 'api/v1/reports/payment-breakdown/'),
            ('GET', 'api/v1/admin/reports/payment-breakdown/export/'),
            ('GET', 'api/v1/admin/reports/shifts/'),
            ('GET', 'api/v1/admin/reports/shifts/export/'),
        ),
        default_roles=REPORTING_ROLES,
    ),
]

PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'business_partners',
        surface='admin',
        group_key='business_partners',
        singular_label='Biznes hamkor',
        plural_label='Biznes hamkorlar',
        list_url='api/v1/admin/platform/business-partners/',
        detail_url='api/v1/admin/platform/business-partners/<uuid:pk>/',
        default_roles=PRODUCT_OWNER_ROLES,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'tariffs',
        surface='admin',
        group_key='tariffs',
        singular_label='Tarif',
        plural_label='Tariflar',
        list_url='api/v1/admin/platform/tariffs/',
        detail_url='api/v1/admin/platform/tariffs/<uuid:pk>/',
        default_roles=PRODUCT_OWNER_ROLES,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'restaurants',
        surface='admin',
        group_key='restaurants',
        singular_label='Restoran',
        plural_label='Restoranlar',
        list_url='api/v1/admin/constructor/restaurants/',
        detail_url='api/v1/admin/constructor/restaurants/<uuid:pk>/',
        default_roles=PARTNER_ROLES,
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
            ('DELETE', 'api/v1/admin/constructor/restaurants/<uuid:pk>/'),
        ),
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'roles',
        surface='admin',
        group_key='roles',
        singular_label='Rol',
        plural_label='Rollar',
        list_url='api/v1/admin/users/roles/',
        detail_url='api/v1/admin/users/roles/<uuid:pk>/',
        default_roles=ROLE_MANAGEMENT_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'users',
        surface='admin',
        group_key='users',
        singular_label='Foydalanuvchi',
        plural_label='Foydalanuvchilar',
        list_url='api/v1/admin/users/',
        detail_url='api/v1/admin/users/<uuid:pk>/',
        default_roles=PRODUCT_OWNER_ROLES,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'employees',
        surface='admin',
        group_key='employees',
        singular_label='Xodim',
        plural_label='Xodimlar',
        list_url='api/v1/admin/employees/',
        detail_url='api/v1/admin/employees/<uuid:pk>/',
        default_roles=EMPLOYEE_MANAGEMENT_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/employees/'),
            ('GET', 'api/v1/admin/employees/roles/'),
        ),
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'catalog_categories',
        surface='admin',
        group_key='catalog',
        singular_label='Menyu bo‘limi',
        plural_label='Menyu bo‘limlari',
        list_url='api/v1/admin/catalog/categories/',
        detail_url='api/v1/admin/catalog/categories/<uuid:pk>/',
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'catalog_items',
        surface='admin',
        group_key='catalog',
        singular_label='Menyu pozitsiyasi',
        plural_label='Menyu pozitsiyalari',
        list_url='api/v1/admin/catalog/items/',
        detail_url='api/v1/admin/catalog/items/<uuid:pk>/',
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('POST', 'api/v1/admin/catalog/items/<uuid:pk>/stoplist/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'halls',
        surface='admin',
        group_key='floor',
        singular_label='Zal',
        plural_label='Zallar',
        list_url='api/v1/admin/floor/halls/',
        detail_url='api/v1/admin/floor/halls/<uuid:pk>/',
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
        list_default_roles=FLOOR_OPERATIONS_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/floor/halls/'),
            ('GET', 'api/v1/pos/halls/'),
        ),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/floor/halls/<uuid:pk>/'),
            ('GET', 'api/v1/admin/floor/halls/<uuid:pk>/constructor/'),
        ),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/floor/halls/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/floor/halls/<uuid:pk>/'),
            ('PUT', 'api/v1/admin/floor/halls/<uuid:pk>/constructor/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'zones',
        surface='admin',
        group_key='floor',
        singular_label='Zona',
        plural_label='Zonalar',
        list_url='api/v1/admin/floor/zones/',
        detail_url='api/v1/admin/floor/zones/<uuid:pk>/',
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'tables',
        surface='admin',
        group_key='floor',
        singular_label='Stol',
        plural_label='Stollar',
        list_url='api/v1/admin/floor/tables/',
        detail_url='api/v1/admin/floor/tables/<uuid:pk>/',
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'table_sessions',
        surface='admin',
        group_key='floor',
        singular_label='Stol sessiyasi',
        plural_label='Stol sessiyalari',
        list_url='api/v1/admin/floor/table-sessions/',
        detail_url='api/v1/admin/floor/table-sessions/<uuid:pk>/',
        default_roles=FLOOR_OPERATIONS_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/floor/table-sessions/'),
            ('GET', 'api/v1/pos/halls/table-sessions/'),
        ),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
            ('GET', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
        ),
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/floor/table-sessions/'),
            ('POST', 'api/v1/pos/halls/table-sessions/'),
        ),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
            ('DELETE', 'api/v1/admin/floor/table-sessions/<uuid:pk>/'),
            ('PUT', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/halls/table-sessions/<uuid:pk>/'),
            ('POST', 'api/v1/pos/halls/table-sessions/<uuid:pk>/move/'),
            ('POST', 'api/v1/pos/halls/table-sessions/<uuid:pk>/merge/'),
        ),
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'cash_desks',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Kassa',
        plural_label='Kassalar',
        list_url='api/v1/admin/constructor/cash-desks/',
        detail_url='api/v1/admin/constructor/cash-desks/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'devices',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Qurilma',
        plural_label='Qurilmalar',
        list_url='api/v1/admin/constructor/devices/',
        detail_url='api/v1/admin/constructor/devices/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'prep_stations',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Tayyorlash stansiyasi',
        plural_label='Tayyorlash stansiyalari',
        list_url='api/v1/admin/constructor/prep-stations/',
        detail_url='api/v1/admin/constructor/prep-stations/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'distribution_points',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Tarqatish nuqtasi',
        plural_label='Tarqatish nuqtalari',
        list_url='api/v1/admin/constructor/distribution-points/',
        detail_url='api/v1/admin/constructor/distribution-points/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'integration_configs',
        surface='admin',
        group_key='integrations',
        singular_label='Integratsiya sozlamasi',
        plural_label='Integratsiya sozlamalari',
        list_url='api/v1/admin/integrations/configs/',
        detail_url='api/v1/admin/integrations/configs/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'orders',
        surface='admin',
        group_key='orders',
        singular_label='Buyurtma',
        plural_label='Buyurtmalar',
        list_url='api/v1/pos/orders/',
        detail_url='api/v1/pos/orders/<uuid:pk>/',
        default_roles=ORDER_VIEW_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/orders/'),
            ('GET', 'api/v1/admin/order-items/'),
            ('GET', 'api/v1/admin/order-item-notes/'),
            ('GET', 'api/v1/pos/orders/'),
        ),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/orders/<uuid:pk>/'),
            ('GET', 'api/v1/admin/order-items/<uuid:pk>/'),
            ('GET', 'api/v1/admin/order-item-notes/<uuid:pk>/'),
            ('GET', 'api/v1/pos/orders/<uuid:pk>/'),
            ('GET', 'api/v1/pos/orders/<uuid:order_id>/items/'),
            ('GET', 'api/v1/pos/orders/items/<uuid:pk>/'),
        ),
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/orders/'),
            ('POST', 'api/v1/pos/orders/<uuid:order_id>/items/'),
        ),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/pos/orders/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/orders/<uuid:pk>/'),
            ('PUT', 'api/v1/pos/orders/items/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/orders/items/<uuid:pk>/'),
            ('DELETE', 'api/v1/pos/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/orders/<uuid:pk>/submit/'),
        ),
        include_delete=False,
        create_default_roles=ORDER_WRITE_ROLES,
        update_default_roles=ORDER_WRITE_ROLES,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'payments',
        surface='admin',
        group_key='payments',
        singular_label='To‘lov',
        plural_label='To‘lovlar',
        list_url='api/v1/admin/payments/',
        detail_url='api/v1/admin/payments/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        include_create=False,
        include_update=False,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'receipts',
        surface='admin',
        group_key='payments',
        singular_label='Chek',
        plural_label='Cheklar',
        list_url='api/v1/admin/receipts/',
        detail_url='api/v1/admin/receipts/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        include_create=False,
        include_update=False,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'kitchen_tickets',
        surface='admin',
        group_key='kitchen',
        singular_label='Oshxona buyurtmasi',
        plural_label='Oshxona buyurtmalari',
        list_url='api/v1/admin/kitchen/tickets/',
        detail_url='api/v1/pos/kitchen/tickets/<uuid:pk>/',
        default_roles=KITCHEN_VIEW_ROLES,
        list_endpoints=endpoint_specs(('GET', 'api/v1/admin/kitchen/tickets/')),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/kitchen/tickets/<uuid:pk>/'),
            ('GET', 'api/v1/pos/kitchen/tickets/<uuid:pk>/'),
        ),
        include_create=False,
        include_delete=False,
        update_surface='pos',
        update_default_roles=KITCHEN_OPERATION_ROLES,
        update_endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/kitchen/tickets/<uuid:pk>/status/'),
            ('POST', 'api/v1/pos/kitchen/items/<uuid:pk>/status/'),
        ),
    )
)

PERMISSION_DEFINITIONS.extend(
    [
        action_permission(
            'business_partners.activate',
            surface='admin',
            group_key='business_partners',
            name='Biznes hamkorni faollashtirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/activate/')),
            default_roles=PRODUCT_OWNER_ROLES,
        ),
        action_permission(
            'business_partners.deactivate',
            surface='admin',
            group_key='business_partners',
            name='Biznes hamkorni faolsizlantirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/deactivate/')),
            default_roles=PRODUCT_OWNER_ROLES,
        ),
        action_permission(
            'business_partners.reset_password',
            surface='admin',
            group_key='business_partners',
            name='Biznes hamkor parolini tiklash',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/reset-password/')),
            default_roles=PRODUCT_OWNER_ROLES,
        ),
        action_permission(
            'restaurants.activate',
            surface='admin',
            group_key='restaurants',
            name='Restoranni faollashtirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/activate/')),
            default_roles=PARTNER_ROLES,
        ),
        action_permission(
            'restaurants.deactivate',
            surface='admin',
            group_key='restaurants',
            name='Restoranni faolsizlantirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/deactivate/')),
            default_roles=PARTNER_ROLES,
        ),
        action_permission(
            'restaurants.reset_password',
            surface='admin',
            group_key='restaurants',
            name='Restoran admini parolini tiklash',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/reset-password/')),
            default_roles=PARTNER_ROLES,
        ),
        action_permission(
            'mxik.search',
            surface='admin',
            group_key='catalog',
            name='MXIK bo‘yicha qidirish',
            endpoints=endpoint_specs(('GET', 'api/v1/admin/catalog/mxik/search/')),
            default_roles=RESTAURANT_ADMIN_UI_ROLES,
            ui_visible=False,
        ),
        action_permission(
            'mxik.view',
            surface='admin',
            group_key='catalog',
            name='MXIK ma’lumotini ko‘rish',
            endpoints=endpoint_specs(('GET', 'api/v1/admin/catalog/mxik/<str:code>/')),
            default_roles=RESTAURANT_ADMIN_UI_ROLES,
            ui_visible=False,
        ),
    ]
)

PERMISSIONS_BY_CODE = {item['code']: item for item in PERMISSION_DEFINITIONS}
CANONICAL_PERMISSION_CODES = frozenset(PERMISSIONS_BY_CODE)
ADMIN_UI_PERMISSION_CODES = frozenset(code for code, item in PERMISSIONS_BY_CODE.items() if item['surface'] in {'admin', 'dashboard'})
POS_UI_PERMISSION_CODES = frozenset(
    {
        'halls.list',
        'table_sessions.list',
        'table_sessions.view',
        'table_sessions.create',
        'table_sessions.update',
        'catalog_menu.view',
        'orders.list',
        'orders.view',
        'orders.create',
        'orders.update',
        'open_checks.list',
        'payments.create',
        'payments.update',
        'kitchen_queue.view',
        'kitchen_tickets.view',
        'kitchen_tickets.update',
    }
)


def build_default_role_map() -> dict[str, dict]:
    role_permissions: dict[str, list[str]] = defaultdict(list)
    for item in PERMISSION_DEFINITIONS:
        for role_code in item['default_roles']:
            role_permissions[role_code].append(item['code'])

    return {
        role_code: {
            'name': metadata['name'],
            'permissions': sorted(role_permissions.get(role_code, [])),
        }
        for role_code, metadata in ROLE_DEFINITIONS.items()
    }


DEFAULT_ROLE_MAP = build_default_role_map()
