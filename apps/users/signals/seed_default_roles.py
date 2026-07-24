from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.users.models import Permission, PermissionEndpoint, Role
from apps.users.permission_registry import DEFAULT_ROLE_MAP, PERMISSION_DEFINITIONS


def apply_translations(instance, field_name, translations):
    setattr(instance, field_name, translations['uz'])
    setattr(instance, f'{field_name}_uz', translations['uz'])
    setattr(instance, f'{field_name}_uz_crl', translations['uz_crl'])
    setattr(instance, f'{field_name}_ru', translations['ru'])


@receiver(post_migrate)
def seed_default_roles_signal(sender, **kwargs):
    if sender.label != 'users':
        return

    permissions_by_code = {}
    active_codes = {item['code'] for item in PERMISSION_DEFINITIONS}
    Permission.objects.exclude(code__in=active_codes).delete()

    for item in PERMISSION_DEFINITIONS:
        permission, _ = Permission.objects.get_or_create(code=item['code'])
        apply_translations(permission, 'name', item['name'])
        apply_translations(permission, 'description', item['description'])
        permission.surface = item['surface']
        permission.resource = item['resource']
        permission.action = item['action']
        permission.ui_visible = item['ui_visible']
        permission.group_key = item['group_key']
        permission.save()

        desired_endpoints = {(endpoint['method'], endpoint['url']) for endpoint in item['endpoints']}
        for method, url in desired_endpoints:
            PermissionEndpoint.objects.get_or_create(
                permission=permission,
                url=url,
                method=method,
            )
        for endpoint in permission.endpoints.all():
            if (endpoint.method, endpoint.url) not in desired_endpoints:
                endpoint.delete()

        permissions_by_code[item['code']] = permission

    PermissionEndpoint.objects.exclude(permission__code__in=active_codes).delete()

    active_role_codes = set(DEFAULT_ROLE_MAP)
    Role.objects.filter(is_system=True).exclude(code__in=active_role_codes).delete()

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

    # Tariffs are a second permission gate. Keep newly introduced capabilities
    # available after every migration, including on a fresh database where
    # permissions are created by this signal only after data migrations run.
    from apps.platform.services.expense_access import grant_default_expense_access
    from apps.platform.services.modifier_access import grant_default_modifier_access

    grant_default_expense_access()
    grant_default_modifier_access()
