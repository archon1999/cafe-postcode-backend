from collections import defaultdict


def t(uz: str, uz_crl: str | None = None, ru: str | None = None) -> dict[str, str]:
    return {
        'uz': uz,
        'uz_crl': uz_crl or uz,
        'ru': ru or uz,
    }


def endpoint_specs(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{'method': method.upper(), 'url': url} for method, url in pairs]


def merge_endpoint_specs(*groups: list[dict[str, str]] | None) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for group in groups:
        if not group:
            continue
        for endpoint in group:
            key = (endpoint['method'].upper(), endpoint['url'])
            if key in seen:
                continue
            seen.add(key)
            merged.append({'method': key[0], 'url': key[1]})

    return merged


def merge_role_sets(*groups: tuple[str, ...] | None) -> tuple[str, ...]:
    merged: list[str] = []

    for group in groups:
        if not group:
            continue
        for role_code in group:
            if role_code not in merged:
                merged.append(role_code)

    return tuple(merged)


ROLE_DEFINITIONS = {
    'product_owner': {'name': t('Platforma mahsulot egasi')},
    'business_partner': {'name': t('Biznes hamkor')},
    'restaurant_admin': {'name': t('Restoran admini')},
    'fast_food_admin': {'name': t('Fast food admini')},
    'manager': {'name': t('Menejer')},
    'cashier': {'name': t('Kassir')},
    'waiter': {'name': t('Ofitsiant')},
    'chef': {'name': t('Oshpaz')},
    'head_chef': {'name': t('Shef oshpaz')},
    'barman': {'name': t('Barmen')},
    'fast_food_manager': {'name': t('Fast food menejeri')},
    'fast_food_cashier': {'name': t('Fast food kassiri')},
}

PRODUCT_OWNER_ROLES = ('product_owner',)
BUSINESS_PARTNER_ROLES = ('business_partner',)
ROLE_MANAGEMENT_ROLES = ()
EMPLOYEE_MANAGEMENT_ROLES = ('restaurant_admin', 'fast_food_admin')
RESTAURANT_ADMIN_UI_ROLES = ('restaurant_admin', 'fast_food_admin')
RESTAURANT_SETUP_ROLES = ('restaurant_admin', 'fast_food_admin')
CATALOG_ADMIN_ROLES = ('restaurant_admin', 'fast_food_admin')
FLOOR_ADMIN_ROLES = ('restaurant_admin',)
ORDER_VIEW_ROLES = ('restaurant_admin', 'fast_food_admin')
PAYMENT_ADMIN_ROLES = ('restaurant_admin', 'fast_food_admin')
REPORTING_ROLES = ('restaurant_admin', 'fast_food_admin')
ADMIN_KITCHEN_ROLES = ('restaurant_admin',)
POS_HALL_VIEW_ROLES = ('cashier', 'waiter', 'manager')
POS_TABLE_MANAGE_ROLES = ('cashier', 'waiter', 'manager')
POS_TABLE_MENU_VIEW_ROLES = ('cashier', 'waiter', 'manager')
POS_TAKEAWAY_MENU_VIEW_ROLES = ('cashier', 'manager', 'fast_food_cashier', 'fast_food_manager')
POS_KITCHEN_VIEW_ROLES = ('chef', 'barman', 'head_chef')
POS_KITCHEN_VIEW_ALL_ROLES = ('head_chef',)
POS_KITCHEN_UPDATE_ROLES = ('chef', 'barman', 'head_chef')
POS_KITCHEN_CANCEL_ROLES = ('head_chef',)
POS_OPEN_CHECKS_VIEW_ROLES = ('cashier', 'manager', 'fast_food_cashier', 'fast_food_manager')
POS_PAYMENT_ORDER_ITEM_CREATE_ROLES = ('fast_food_cashier', 'fast_food_manager')
POS_PAYMENT_ORDER_ITEM_DELETE_ROLES = ('fast_food_cashier', 'fast_food_manager')
POS_PAYMENT_OPERATION_ROLES = ('cashier', 'manager', 'fast_food_cashier', 'fast_food_manager')
POS_CASH_SHIFT_VIEW_ROLES = ('manager', 'fast_food_manager')
POS_CASH_SHIFT_MANAGE_ROLES = ('manager', 'fast_food_manager')
POS_CASH_EXPENSE_ROLES = ('manager', 'fast_food_manager')
POS_FISCAL_RECEIPT_SKIP_ROLES = ('cashier', 'manager', 'fast_food_cashier', 'fast_food_manager')
POS_FISCAL_SHIFT_MANAGE_ROLES = ('manager', 'fast_food_manager')
POS_TABLE_RESERVATION_ROLES = ('cashier', 'manager')
CASHIER_ROLES = POS_OPEN_CHECKS_VIEW_ROLES
PAYMENT_OPERATION_ROLES = POS_PAYMENT_OPERATION_ROLES
KITCHEN_OPERATION_ROLES = POS_KITCHEN_VIEW_ROLES


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
            f'{code_prefix}.view',
            surface=view_surface or list_surface or surface,
            resource=code_prefix,
            action='view',
            ui_visible=True,
            group_key=group_key,
            name=f"{plural_label}ni ko'rish",
            endpoints=merge_endpoint_specs(
                list_endpoints or endpoint_specs(('GET', list_url)),
                view_endpoints or endpoint_specs(('GET', detail_url)),
            ),
            default_roles=merge_role_sets(list_default_roles, view_default_roles, default_roles),
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
                name=f"{singular_label}ni o'chirish",
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
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/local-agents/'),
            ('POST', 'api/v1/admin/local-agents/bulk-action/'),
            ('GET', 'api/v1/admin/local-agents/<uuid:pk>/diagnostics/'),
            ('GET', 'api/v1/admin/local-agents/<uuid:pk>/logs/'),
            ('POST', 'api/v1/admin/local-agents/<uuid:pk>/outbox/<str:operation_id>/'),
            ('POST', 'api/v1/admin/local-agents/<uuid:pk>/update-now/'),
            ('POST', 'api/v1/admin/telegram-reports/link-token/'),
            ('GET', 'api/v1/admin/telegram-reports/subscriptions/'),
            ('DELETE', 'api/v1/admin/telegram-reports/subscriptions/<uuid:pk>/'),
            ('GET', 'api/v1/admin/devices/'),
            ('GET', 'api/v1/admin/devices/migration-summary/'),
            ('GET', 'api/v1/admin/devices/pairings/'),
            ('POST', 'api/v1/admin/devices/pairings/<uuid:pairing_id>/approve/'),
            ('POST', 'api/v1/admin/devices/pairings/<uuid:pairing_id>/reject/'),
            ('GET', 'api/v1/admin/devices/<uuid:pk>/'),
            ('POST', 'api/v1/admin/devices/<uuid:pk>/revoke/'),
        ),
        default_roles=PRODUCT_OWNER_ROLES,
    ),
    action_permission(
        'control.branches.view',
        surface='admin',
        group_key='devices',
        name='Control ilovasida biriktirilgan shahobcha va qurilmalarni ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/control/branches/'),
            ('GET', 'api/v1/admin/control/branches/<uuid:restaurant_id>/devices/'),
        ),
        default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
    ),
    action_permission(
        'control.pairings.manage',
        surface='admin',
        group_key='devices',
        name='Control ilovasida qurilmalarni ulash',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/control/pairings/resolve/'),
            (
                'POST',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/approve/',
            ),
            (
                'POST',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/pairings/<uuid:pairing_id>/reject/',
            ),
        ),
        default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
    ),
    action_permission(
        'control.devices.revoke',
        surface='admin',
        group_key='devices',
        name='Control ilovasida qurilma ulanishini bekor qilish',
        endpoints=endpoint_specs(
            (
                'POST',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/devices/<uuid:device_id>/revoke/',
            ),
        ),
        default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
    ),
    action_permission(
        'control.telegram.manage',
        surface='admin',
        group_key='devices',
        name='Control ilovasida Telegram hisobot ulanishlarini boshqarish',
        endpoints=endpoint_specs(
            (
                'GET',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/telegram-subscriptions/',
            ),
            (
                'POST',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/telegram-link/',
            ),
            (
                'POST',
                'api/v1/admin/control/branches/<uuid:restaurant_id>/telegram-subscriptions/<uuid:subscription_id>/revoke/',
            ),
        ),
        default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
    ),
    permission_definition(
        'security_events.view',
        surface='admin',
        resource='security_events',
        action='view',
        ui_visible=True,
        group_key='security',
        name='Xavfsizlik hodisalarini ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/security-events/'),
            ('POST', 'api/v1/admin/security-events/<uuid:pk>/acknowledge/'),
        ),
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
    ),
    permission_definition(
        'dashboard.view',
        surface='dashboard',
        resource='dashboard',
        action='view',
        ui_visible=True,
        group_key='dashboard',
        name='Dashboardni ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/dashboard/auth/me/'),
            ('GET', 'api/v1/dashboard/overview/'),
            ('GET', 'api/v1/dashboard/open-checks/'),
            ('GET', 'api/v1/dashboard/top-items/'),
            ('GET', 'api/v1/dashboard/staff/'),
            ('GET', 'api/v1/dashboard/shifts/'),
        ),
        default_roles=RESTAURANT_ADMIN_UI_ROLES,
    ),
    permission_definition(
        'permissions.view',
        surface='admin',
        resource='permissions',
        action='view',
        ui_visible=True,
        group_key='permissions',
        name='Ruxsatlar katalogini ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/permissions/'),
            ('GET', 'api/v1/admin/permissions/options/'),
        ),
        default_roles=ROLE_MANAGEMENT_ROLES,
    ),
    permission_definition(
        'restaurants.custom_tariff',
        surface='admin',
        resource='restaurants',
        action='custom_tariff',
        ui_visible=True,
        group_key='restaurants',
        name='Restoran uchun maxsus tarif berish',
        description='Biznes hamkorga restoran aktivatsiyasida maxsus tarif tanlash ruxsati',
        default_roles=(),
    ),
    permission_definition(
        'restaurant_settings.view',
        surface='admin',
        resource='restaurant_settings',
        action='view',
        ui_visible=True,
        group_key='restaurant_settings',
        name='Restoran sozlamalarini ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/restaurants/settings/'),
            ('GET', 'api/v1/admin/restaurants/my-restaurant/'),
        ),
        default_roles=RESTAURANT_SETUP_ROLES,
    ),
    permission_definition(
        'restaurant_settings.update',
        surface='admin',
        resource='restaurant_settings',
        action='update',
        ui_visible=True,
        group_key='restaurant_settings',
        name='Restoran sozlamalarini tahrirlash',
        endpoints=endpoint_specs(('PUT', 'api/v1/admin/restaurants/settings/'), ('PATCH', 'api/v1/admin/restaurants/settings/')),
        default_roles=RESTAURANT_SETUP_ROLES,
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
        default_roles=('restaurant_admin', 'cashier', 'waiter', 'universal_operator'),
    ),
    permission_definition(
        'open_checks.view',
        surface='pos',
        resource='open_checks',
        action='view',
        ui_visible=True,
        group_key='payments',
        name='Ochiq cheklar ro‘yxatini ko‘rish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/billing/open-checks/'),
            ('GET', 'api/v1/pos/billing/context/'),
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
        endpoints=endpoint_specs(('POST', 'api/v1/pos/billing/orders/<uuid:pk>/pay/')),
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
            ('POST', 'api/v1/pos/billing/<uuid:pk>/refund/'),
            ('GET', 'api/v1/pos/billing/qz/certificate/'),
            ('POST', 'api/v1/pos/billing/qz/sign/'),
            ('POST', 'api/v1/pos/billing/payments/<uuid:pk>/print-document/'),
            ('POST', 'api/v1/pos/billing/orders/<uuid:pk>/precheck/print-document/'),
            ('POST', 'api/v1/pos/printing/jobs/'),
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
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/kitchen/queue/'),
            ('GET', 'api/v1/pos/monitor/kitchen-queue/'),
        ),
        default_roles=KITCHEN_OPERATION_ROLES,
    ),
    permission_definition(
        'pos_halls.view',
        surface='pos',
        resource='pos_halls',
        action='view',
        ui_visible=True,
        group_key='floor',
        name="POS zallarni ko'rish",
        endpoints=endpoint_specs(('GET', 'api/v1/pos/floor/halls/')),
        default_roles=POS_HALL_VIEW_ROLES,
    ),
    permission_definition(
        'pos_tables.manage',
        surface='pos',
        resource='pos_tables',
        action='manage',
        ui_visible=True,
        group_key='floor',
        name="POS stollarni boshqarish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/floor/table-sessions/'),
            ('GET', 'api/v1/pos/floor/table-sessions/<uuid:pk>/'),
            ('POST', 'api/v1/pos/floor/table-sessions/'),
            ('PUT', 'api/v1/pos/floor/table-sessions/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/floor/table-sessions/<uuid:pk>/'),
            ('POST', 'api/v1/pos/floor/table-sessions/<uuid:pk>/move/'),
            ('POST', 'api/v1/pos/floor/table-sessions/<uuid:pk>/merge/'),
            ('GET', 'api/v1/pos/sales/orders/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('PUT', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:order_id>/items/'),
            ('GET', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/sales/orders/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/bulk/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/scan-marking/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:order_id>/marking-status/'),
            ('PUT', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('DELETE', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:pk>/submit/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:pk>/serve-ready/'),
            ('POST', 'api/v1/pos/billing/orders/<uuid:pk>/precheck/print-document/'),
            ('POST', 'api/v1/pos/catalog/scan/'),
            ('GET', 'api/v1/pos/billing/qz/certificate/'),
            ('POST', 'api/v1/pos/billing/qz/sign/'),
        ),
        default_roles=POS_TABLE_MANAGE_ROLES,
    ),
    permission_definition(
        'pos_table_menu.view',
        surface='pos',
        resource='pos_table_menu',
        action='view',
        ui_visible=True,
        group_key='catalog',
        name="POS stol menyusini ko'rish",
        endpoints=endpoint_specs(('GET', 'api/v1/pos/catalog/menu/')),
        default_roles=POS_TABLE_MENU_VIEW_ROLES,
    ),
    permission_definition(
        'pos_takeaway_menu.view',
        surface='pos',
        resource='pos_takeaway_menu',
        action='view',
        ui_visible=True,
        group_key='catalog',
        name="POS olib ketish menyusini ko'rish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/catalog/menu/'),
            ('GET', 'api/v1/pos/sales/orders/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('PUT', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/sales/orders/<uuid:pk>/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:order_id>/items/'),
            ('GET', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/sales/orders/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/bulk/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/scan-marking/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:order_id>/marking-status/'),
            ('PUT', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('PATCH', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('DELETE', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:pk>/submit/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:pk>/serve-ready/'),
            ('POST', 'api/v1/pos/billing/orders/<uuid:pk>/precheck/print-document/'),
            ('POST', 'api/v1/pos/catalog/scan/'),
            ('GET', 'api/v1/pos/billing/qz/certificate/'),
            ('POST', 'api/v1/pos/billing/qz/sign/'),
        ),
        default_roles=POS_TAKEAWAY_MENU_VIEW_ROLES,
    ),
    permission_definition(
        'pos_kitchen_orders.view',
        surface='pos',
        resource='pos_kitchen_orders',
        action='view',
        ui_visible=True,
        group_key='kitchen',
        name="POS oshxona buyurtmalarini ko'rish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/kitchen/queue/'),
            ('GET', 'api/v1/pos/monitor/kitchen-queue/'),
            ('GET', 'api/v1/pos/kitchen/tickets/<uuid:pk>/'),
        ),
        default_roles=POS_KITCHEN_VIEW_ROLES,
    ),
    permission_definition(
        'pos_kitchen_orders.update',
        surface='pos',
        resource='pos_kitchen_orders',
        action='update',
        ui_visible=True,
        group_key='kitchen',
        name="POS oshxona buyurtmalarini tahrirlash",
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/kitchen/tickets/<uuid:pk>/status/'),
            ('POST', 'api/v1/pos/kitchen/tickets/<uuid:pk>/announce/'),
            ('POST', 'api/v1/pos/kitchen/items/<uuid:pk>/status/'),
        ),
        default_roles=POS_KITCHEN_UPDATE_ROLES,
    ),
    permission_definition(
        'pos_kitchen_orders.view_all',
        surface='pos',
        resource='pos_kitchen_orders',
        action='view_all',
        ui_visible=True,
        group_key='kitchen',
        name="POS oshxona barcha buyurtmalarini ko'rish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/kitchen/queue/'),
            ('GET', 'api/v1/pos/monitor/kitchen-queue/'),
            ('GET', 'api/v1/pos/kitchen/tickets/<uuid:pk>/'),
        ),
        default_roles=POS_KITCHEN_VIEW_ALL_ROLES,
    ),
    permission_definition(
        'pos_kitchen_orders.cancel',
        surface='pos',
        resource='pos_kitchen_orders',
        action='cancel',
        ui_visible=True,
        group_key='kitchen',
        name='POS oshxona buyurtmasini bekor qilish',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/kitchen/items/<uuid:pk>/status/'),
        ),
        default_roles=POS_KITCHEN_CANCEL_ROLES,
    ),
    permission_definition(
        'pos_open_checks.view',
        surface='pos',
        resource='pos_open_checks',
        action='view',
        ui_visible=True,
        group_key='payments',
        name="POS ochiq hisoblarni ko'rish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/billing/open-checks/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:pk>/'),
        ),
        default_roles=POS_OPEN_CHECKS_VIEW_ROLES,
    ),
    permission_definition(
        'pos_payment_order_items.create',
        surface='pos',
        resource='pos_payment_order_items',
        action='create',
        ui_visible=True,
        group_key='payments',
        name="POS to'lov oynasidan mahsulot qo'shish",
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/items/bulk/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/scan-marking/'),
        ),
        default_roles=POS_PAYMENT_ORDER_ITEM_CREATE_ROLES,
    ),
    permission_definition(
        'pos_payment_order_items.delete',
        surface='pos',
        resource='pos_payment_order_items',
        action='delete',
        ui_visible=True,
        group_key='payments',
        name="POS to'lov oynasidan mahsulot kamaytirish",
        endpoints=endpoint_specs(
            ('DELETE', 'api/v1/pos/sales/orders/items/<uuid:pk>/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/scan-marking/'),
        ),
        default_roles=POS_PAYMENT_ORDER_ITEM_DELETE_ROLES,
    ),
    permission_definition(
        'pos_payments.create',
        surface='pos',
        resource='pos_payments',
        action='create',
        ui_visible=True,
        group_key='payments',
        name="POS to'lov amallarini bajarish",
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/billing/context/'),
            ('POST', 'api/v1/pos/billing/orders/<uuid:pk>/pay/'),
            ('POST', 'api/v1/pos/billing/orders/<uuid:pk>/card-payments/initiate/'),
            ('POST', 'api/v1/pos/billing/payments/<uuid:pk>/terminal-result/'),
            ('POST', 'api/v1/pos/billing/payments/<uuid:pk>/retry-fiscal/'),
            ('POST', 'api/v1/pos/billing/<uuid:pk>/refund/'),
            ('POST', 'api/v1/pos/sales/orders/<uuid:order_id>/scan-marking/'),
            ('GET', 'api/v1/pos/sales/orders/<uuid:order_id>/marking-status/'),
            ('GET', 'api/v1/pos/billing/qz/certificate/'),
            ('POST', 'api/v1/pos/billing/qz/sign/'),
            ('POST', 'api/v1/pos/billing/payments/<uuid:pk>/print-document/'),
            ('POST', 'api/v1/pos/printing/jobs/'),
        ),
        default_roles=POS_PAYMENT_OPERATION_ROLES,
    ),
    permission_definition(
        'pos_cash_shift.view',
        surface='pos',
        resource='pos_cash_shift',
        action='view',
        ui_visible=True,
        group_key='payments',
        name="POS kassa smenasini ko'rish",
        default_roles=POS_CASH_SHIFT_VIEW_ROLES,
    ),
    permission_definition(
        'pos_cash_shift.manage',
        surface='pos',
        resource='pos_cash_shift',
        action='manage',
        ui_visible=True,
        group_key='payments',
        name='POS kassa smenasini boshqarish',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/billing/shifts/open/'),
            ('POST', 'api/v1/pos/billing/shifts/current/close/'),
            ('POST', 'api/v1/pos/billing/shifts/current/print-report/'),
        ),
        default_roles=POS_CASH_SHIFT_MANAGE_ROLES,
    ),
    permission_definition(
        'pos_cash_expenses.create',
        surface='pos',
        resource='pos_cash_expenses',
        action='create',
        ui_visible=True,
        group_key='payments',
        name='POS kassadan xarajat kiritish',
        endpoints=endpoint_specs(
            ('GET', 'api/v1/pos/billing/expense-categories/'),
            ('GET', 'api/v1/pos/billing/shifts/current/expenses/'),
            ('POST', 'api/v1/pos/billing/shifts/current/expenses/'),
        ),
        default_roles=POS_CASH_EXPENSE_ROLES,
    ),
    permission_definition(
        'pos_cash_expenses.void',
        surface='pos',
        resource='pos_cash_expenses',
        action='void',
        ui_visible=True,
        group_key='payments',
        name='POS kassa xarajatini bekor qilish',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/billing/expenses/<uuid:pk>/void/'),
        ),
        default_roles=POS_CASH_EXPENSE_ROLES,
    ),
    permission_definition(
        'pos_fiscal_receipts.skip',
        surface='pos',
        resource='pos_fiscal_receipts',
        action='skip',
        ui_visible=True,
        group_key='payments',
        name="POS fiscal chek yuborishni o'chirish",
        endpoints=endpoint_specs(('POST', 'api/v1/pos/billing/orders/<uuid:pk>/pay/')),
        default_roles=POS_FISCAL_RECEIPT_SKIP_ROLES,
    ),
    permission_definition(
        'pos_fiscal_shift.manage',
        surface='pos',
        resource='pos_fiscal_shift',
        action='manage',
        ui_visible=True,
        group_key='payments',
        name='POS fiscal smenani boshqarish',
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/billing/fiscal-shifts/open/'),
            ('POST', 'api/v1/pos/billing/fiscal-shifts/close/'),
        ),
        default_roles=POS_FISCAL_SHIFT_MANAGE_ROLES,
    ),
    permission_definition(
        'pos_table_reservations.manage',
        surface='pos',
        resource='pos_table_reservations',
        action='manage',
        ui_visible=True,
        group_key='floor',
        name="POS stolni bronlash va bron stolni ochish",
        endpoints=endpoint_specs(
            ('POST', 'api/v1/pos/floor/tables/<uuid:pk>/reserve/'),
            ('POST', 'api/v1/pos/floor/table-sessions/'),
        ),
        default_roles=POS_TABLE_RESERVATION_ROLES,
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
            ('GET', 'api/v1/admin/reporting/summary/'),
            ('GET', 'api/v1/admin/reporting/summary/export/'),
            ('GET', 'api/v1/admin/reporting/sales/'),
            ('GET', 'api/v1/admin/reporting/sales/export/'),
            ('GET', 'api/v1/admin/reporting/open-checks/'),
            ('GET', 'api/v1/admin/reporting/open-checks/export/'),
            ('GET', 'api/v1/admin/reporting/receipts/'),
            ('GET', 'api/v1/admin/reporting/receipts/export/'),
            ('GET', 'api/v1/admin/reporting/top-items/'),
            ('GET', 'api/v1/admin/reporting/top-items/export/'),
            ('GET', 'api/v1/admin/reporting/top-staff/'),
            ('GET', 'api/v1/admin/reporting/top-staff/export/'),
            ('GET', 'api/v1/admin/reporting/payment-breakdown/'),
            ('GET', 'api/v1/admin/reporting/payment-breakdown/export/'),
            ('GET', 'api/v1/admin/reporting/shifts/'),
            ('GET', 'api/v1/admin/reporting/shifts/export/'),
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
        create_endpoints=merge_endpoint_specs(
            endpoint_specs(('POST', 'api/v1/admin/platform/business-partners/')),
            endpoint_specs(('GET', 'api/v1/admin/platform/business-partners/lookup/')),
        ),
        update_endpoints=merge_endpoint_specs(
            endpoint_specs(
                ('PUT', 'api/v1/admin/platform/business-partners/<uuid:pk>/'),
                ('PATCH', 'api/v1/admin/platform/business-partners/<uuid:pk>/'),
            ),
            endpoint_specs(('GET', 'api/v1/admin/platform/business-partners/lookup/')),
        ),
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
        list_url='api/v1/admin/restaurants/',
        detail_url='api/v1/admin/restaurants/<uuid:pk>/',
        default_roles=BUSINESS_PARTNER_ROLES,
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/restaurants/portfolio-summary/'),
            ('GET', 'api/v1/admin/restaurants/<uuid:pk>/'),
            ('GET', 'api/v1/admin/restaurants/<uuid:pk>/detail/'),
        ),
        create_endpoints=merge_endpoint_specs(
            endpoint_specs(
                ('POST', 'api/v1/admin/restaurants/'),
                ('POST', 'api/v1/admin/restaurants/<uuid:pk>/branches/'),
            ),
            endpoint_specs(('GET', 'api/v1/admin/restaurants/lookup/')),
        ),
        update_endpoints=merge_endpoint_specs(
            endpoint_specs(
                ('PUT', 'api/v1/admin/restaurants/<uuid:pk>/'),
                ('PATCH', 'api/v1/admin/restaurants/<uuid:pk>/'),
                ('DELETE', 'api/v1/admin/restaurants/<uuid:pk>/'),
            ),
            endpoint_specs(('GET', 'api/v1/admin/restaurants/lookup/')),
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
        list_url='api/v1/admin/roles/',
        detail_url='api/v1/admin/roles/<uuid:pk>/',
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
        default_roles=(),
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
        default_roles=CATALOG_ADMIN_ROLES,
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/catalog/categories/'),
            ('POST', 'api/v1/admin/catalog/translations/name/'),
        ),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/catalog/categories/<uuid:pk>/'),
            ('POST', 'api/v1/admin/catalog/translations/name/'),
        ),
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
        default_roles=CATALOG_ADMIN_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/catalog/items/'),
            ('GET', 'api/v1/admin/catalog/item-groups/'),
        ),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('GET', 'api/v1/admin/catalog/item-groups/<uuid:pk>/'),
        ),
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/catalog/items/'),
            ('POST', 'api/v1/admin/catalog/item-groups/'),
            ('POST', 'api/v1/admin/catalog/translations/name/'),
        ),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('POST', 'api/v1/admin/catalog/items/<uuid:pk>/stoplist/'),
            ('POST', 'api/v1/admin/catalog/translations/name/'),
            ('PUT', 'api/v1/admin/catalog/item-groups/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/catalog/item-groups/<uuid:pk>/'),
        ),
        delete_endpoints=endpoint_specs(
            ('DELETE', 'api/v1/admin/catalog/items/<uuid:pk>/'),
            ('DELETE', 'api/v1/admin/catalog/item-groups/<uuid:pk>/'),
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
        default_roles=FLOOR_ADMIN_ROLES,
        list_endpoints=endpoint_specs(('GET', 'api/v1/admin/floor/halls/')),
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
        default_roles=FLOOR_ADMIN_ROLES,
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
        default_roles=FLOOR_ADMIN_ROLES,
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
        default_roles=FLOOR_ADMIN_ROLES,
        list_endpoints=endpoint_specs(('GET', 'api/v1/admin/floor/table-sessions/')),
        view_endpoints=endpoint_specs(('GET', 'api/v1/admin/floor/table-sessions/<uuid:pk>/')),
        include_create=False,
        include_update=False,
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
        list_url='api/v1/admin/restaurants/cash-desks/',
        detail_url='api/v1/admin/restaurants/cash-desks/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/restaurants/cash-desks/'),
            ('GET', 'api/v1/admin/restaurants/setup/readiness/'),
        ),
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/restaurants/cash-desks/'),
            ('POST', 'api/v1/admin/restaurants/setup/apply/'),
            ('POST', 'api/v1/local-agent/enrollment-token/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'prep_stations',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Tayyorlash stansiyasi',
        plural_label='Tayyorlash stansiyalari',
        list_url='api/v1/admin/restaurants/prep-stations/',
        detail_url='api/v1/admin/restaurants/prep-stations/<uuid:pk>/',
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
        list_url='api/v1/admin/restaurants/distribution-points/',
        detail_url='api/v1/admin/restaurants/distribution-points/<uuid:pk>/',
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
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/integrations/configs/'),
            ('GET', 'api/v1/admin/integrations/fiscal-devices/'),
            ('POST', 'api/v1/admin/integrations/marta/check/'),
            ('GET', 'api/v1/local-agent/status/'),
            ('GET', 'api/v1/local-agent/diagnostics/'),
            ('GET', 'api/v1/local-agent/logs/'),
            ('POST', 'api/v1/local-agent/update-now/'),
            ('POST', 'api/v1/local-agent/printer/check/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'catalog_modifier_groups',
        surface='admin',
        group_key='catalog',
        singular_label='Mahsulot xususiyati',
        plural_label='Mahsulot xususiyatlari',
        list_url='api/v1/admin/catalog/modifier-groups/',
        detail_url='api/v1/admin/catalog/modifier-groups/<uuid:pk>/',
        default_roles=CATALOG_ADMIN_ROLES,
        create_endpoints=endpoint_specs(('POST', 'api/v1/admin/catalog/modifier-groups/')),
        update_endpoints=endpoint_specs(
            ('PUT', 'api/v1/admin/catalog/modifier-groups/<uuid:pk>/'),
            ('PATCH', 'api/v1/admin/catalog/modifier-groups/<uuid:pk>/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'print_templates',
        surface='admin',
        group_key='restaurant_setup',
        singular_label='Chek shabloni',
        plural_label='Chek shablonlari',
        list_url='api/v1/admin/printing/templates/',
        detail_url='api/v1/admin/printing/templates/<uuid:pk>/',
        default_roles=RESTAURANT_SETUP_ROLES,
        include_delete=False,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/printing/templates/'),
            ('GET', 'api/v1/admin/printing/presets/'),
        ),
        create_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/printing/templates/<uuid:pk>/versions/'),
        ),
        update_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/printing/templates/<uuid:pk>/versions/<uuid:version_pk>/publish/'),
        ),
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'orders',
        surface='admin',
        group_key='orders',
        singular_label='Buyurtma',
        plural_label='Buyurtmalar',
        list_url='api/v1/admin/sales/orders/',
        detail_url='api/v1/admin/sales/orders/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        list_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/sales/orders/'),
            ('GET', 'api/v1/admin/sales/order-items/'),
            ('GET', 'api/v1/admin/sales/order-item-notes/'),
        ),
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/sales/orders/<uuid:pk>/'),
            ('GET', 'api/v1/admin/sales/order-items/<uuid:pk>/'),
            ('GET', 'api/v1/admin/sales/order-item-notes/<uuid:pk>/'),
        ),
        include_create=False,
        include_update=False,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'payments',
        surface='admin',
        group_key='payments',
        singular_label='To‘lov',
        plural_label='To‘lovlar',
        list_url='api/v1/admin/billing/payments/',
        detail_url='api/v1/admin/billing/payments/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/billing/payments/'),
            ('GET', 'api/v1/admin/billing/payments/<uuid:pk>/'),
            ('POST', 'api/v1/admin/billing/payments/<uuid:pk>/retry-fiscal/'),
        ),
        include_create=False,
        include_update=False,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'expense_categories',
        surface='admin',
        group_key='expenses',
        singular_label='Xarajat kategoriyasi',
        plural_label='Xarajat kategoriyalari',
        list_url='api/v1/admin/billing/expense-categories/',
        detail_url='api/v1/admin/billing/expense-categories/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        include_delete=False,
    )
)
PERMISSION_DEFINITIONS.extend(
    crud_permissions(
        'expenses',
        surface='admin',
        group_key='expenses',
        singular_label='Xarajat',
        plural_label='Xarajatlar',
        list_url='api/v1/admin/billing/expenses/',
        detail_url='api/v1/admin/billing/expenses/<uuid:pk>/',
        default_roles=PAYMENT_ADMIN_ROLES,
        view_endpoints=endpoint_specs(
            ('GET', 'api/v1/admin/billing/expenses/'),
            ('GET', 'api/v1/admin/billing/expenses/<uuid:pk>/'),
        ),
        update_endpoints=endpoint_specs(
            ('POST', 'api/v1/admin/billing/expenses/<uuid:pk>/void/'),
        ),
        include_create=False,
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
        list_url='api/v1/admin/billing/receipts/',
        detail_url='api/v1/admin/billing/receipts/<uuid:pk>/',
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
        detail_url='api/v1/admin/kitchen/tickets/<uuid:pk>/',
        default_roles=ADMIN_KITCHEN_ROLES,
        list_endpoints=endpoint_specs(('GET', 'api/v1/admin/kitchen/tickets/')),
        view_endpoints=endpoint_specs(('GET', 'api/v1/admin/kitchen/tickets/<uuid:pk>/')),
        include_create=False,
        include_update=False,
        include_delete=False,
    )
)

PERMISSION_DEFINITIONS.extend(
    [
        action_permission(
            'business_partners.activate',
            surface='admin',
            group_key='business_partners',
            name='Biznes hamkorni faollashtirish',
            endpoints=endpoint_specs(
                ('GET', 'api/v1/admin/platform/business-partners/<uuid:pk>/activation-defaults/'),
                ('POST', 'api/v1/admin/platform/business-partners/<uuid:pk>/activate/'),
            ),
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
            'business_partners.lookup',
            surface='admin',
            group_key='business_partners',
            name='Biznes hamkorni INN bo‘yicha qidirish',
            endpoints=endpoint_specs(('GET', 'api/v1/admin/platform/business-partners/lookup/')),
            default_roles=PRODUCT_OWNER_ROLES,
            ui_visible=False,
        ),
        action_permission(
            'tariff_options.view',
            surface='admin',
            group_key='tariffs',
            name='Faol tarif variantlarini ko‘rish',
            endpoints=endpoint_specs(('GET', 'api/v1/admin/platform/tariff-options/')),
            default_roles=BUSINESS_PARTNER_ROLES,
            ui_visible=False,
        ),
        action_permission(
            'tariff_roles.view',
            surface='admin',
            group_key='tariffs',
            name="Tarif uchun rollar ro'yxatini ko'rish",
            endpoints=endpoint_specs(('GET', 'api/v1/admin/roles/')),
            default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
            ui_visible=False,
        ),
        action_permission(
            'tariff_permissions.view',
            surface='admin',
            group_key='tariffs',
            name="Tarif uchun ruxsatlar ro'yxatini ko'rish",
            endpoints=endpoint_specs(('GET', 'api/v1/admin/permissions/options/')),
            default_roles=merge_role_sets(PRODUCT_OWNER_ROLES, BUSINESS_PARTNER_ROLES),
            ui_visible=False,
        ),
        action_permission(
            'restaurants.lookup',
            surface='admin',
            group_key='restaurants',
            name="Restoranni STIR bo'yicha qidirish",
            endpoints=endpoint_specs(('GET', 'api/v1/admin/restaurants/lookup/')),
            default_roles=BUSINESS_PARTNER_ROLES,
            ui_visible=False,
        ),
        action_permission(
            'restaurants.activation_options',
            surface='admin',
            group_key='restaurants',
            name='Restoran aktivatsiyasi uchun variantlarni ko‘rish',
            endpoints=endpoint_specs(('GET', 'api/v1/admin/platform/restaurants/activation-options/')),
            default_roles=BUSINESS_PARTNER_ROLES,
            ui_visible=False,
        ),
        action_permission(
            'restaurants.activate',
            surface='admin',
            group_key='restaurants',
            name='Restoranni faollashtirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/activate/')),
            default_roles=BUSINESS_PARTNER_ROLES,
        ),
        action_permission(
            'restaurants.deactivate',
            surface='admin',
            group_key='restaurants',
            name='Restoranni faolsizlantirish',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/deactivate/')),
            default_roles=BUSINESS_PARTNER_ROLES,
        ),
        action_permission(
            'restaurants.change_tariff',
            surface='admin',
            group_key='restaurants',
            name='Restoran tarifini o‘zgartirish',
            endpoints=endpoint_specs(
                ('GET', 'api/v1/admin/platform/restaurants/<uuid:pk>/tariff-change/'),
                ('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/tariff-change/'),
            ),
            default_roles=BUSINESS_PARTNER_ROLES,
        ),
        action_permission(
            'restaurants.reset_password',
            surface='admin',
            group_key='restaurants',
            name='Restoran admini parolini tiklash',
            endpoints=endpoint_specs(('POST', 'api/v1/admin/platform/restaurants/<uuid:pk>/reset-password/')),
            default_roles=BUSINESS_PARTNER_ROLES,
        ),
    ]
)

PERMISSION_DEFINITIONS = [
    item
    for item in PERMISSION_DEFINITIONS
    if item['code']
    not in {
        'business_partners.lookup',
        'catalog_menu.view',
        'open_checks.view',
        'payments.create',
        'payments.update',
        'kitchen_queue.view',
    }
]

PERMISSIONS_BY_CODE = {item['code']: item for item in PERMISSION_DEFINITIONS}
CANONICAL_PERMISSION_CODES = frozenset(PERMISSIONS_BY_CODE)
ADMIN_UI_PERMISSION_CODES = frozenset(code for code, item in PERMISSIONS_BY_CODE.items() if item['surface'] == 'admin')
POS_UI_PERMISSION_CODES = frozenset(
    {
        'pos_halls.view',
        'pos_tables.manage',
        'pos_table_menu.view',
        'pos_takeaway_menu.view',
        'pos_kitchen_orders.view',
        'pos_kitchen_orders.view_all',
        'pos_kitchen_orders.update',
        'pos_kitchen_orders.cancel',
        'pos_open_checks.view',
        'pos_payment_order_items.create',
        'pos_payment_order_items.delete',
        'pos_payments.create',
        'pos_cash_shift.view',
        'pos_cash_shift.manage',
        'pos_cash_expenses.create',
        'pos_cash_expenses.void',
        'pos_fiscal_receipts.skip',
        'pos_fiscal_shift.manage',
        'pos_table_reservations.manage',
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


