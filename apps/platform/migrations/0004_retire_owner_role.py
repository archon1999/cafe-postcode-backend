from django.db import migrations


RESTAURANT_LOGIN_ROLE_CODES = ('restaurant_admin', 'fast_food_admin')


def retire_owner_role(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Role = apps.get_model('users', 'Role')
    User = apps.get_model('users', 'User')
    Tariff = apps.get_model('platform', 'Tariff')
    RestaurantEntitlement = apps.get_model('platform', 'RestaurantEntitlement')

    dashboard_permission = Permission.objects.filter(code='dashboard.view').first()
    if dashboard_permission is not None:
        for role in Role.objects.filter(code__in=RESTAURANT_LOGIN_ROLE_CODES):
            role.permissions.add(dashboard_permission)

        for tariff in Tariff.objects.filter(allowed_roles__code__in=RESTAURANT_LOGIN_ROLE_CODES).distinct():
            tariff.permissions.add(dashboard_permission)

        for entitlement in RestaurantEntitlement.objects.filter(
            allowed_roles__code__in=RESTAURANT_LOGIN_ROLE_CODES
        ).distinct():
            entitlement.permissions.add(dashboard_permission)

    owner_role = Role.objects.filter(code='owner').first()
    if owner_role is None:
        return

    User.objects.filter(role=owner_role, restaurant_profile__isnull=False).delete()
    owner_role.delete()


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0001_initial'),
        ('platform', '0003_restaurantentitlement_billing_period_and_more'),
    ]

    operations = [
        migrations.RunPython(retire_owner_role, migrations.RunPython.noop),
    ]
