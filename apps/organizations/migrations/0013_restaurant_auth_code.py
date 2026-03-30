from django.db import migrations, models

from apps.organizations.models.restaurant import generate_restaurant_auth_code


def populate_restaurant_auth_codes(apps, schema_editor):
    Restaurant = apps.get_model('organizations', 'Restaurant')
    used_codes = set(Restaurant.objects.exclude(auth_code__isnull=True).exclude(auth_code='').values_list('auth_code', flat=True))

    for restaurant in Restaurant.objects.filter(models.Q(auth_code__isnull=True) | models.Q(auth_code='')).iterator():
        auth_code = generate_restaurant_auth_code()
        while auth_code in used_codes:
            auth_code = generate_restaurant_auth_code()
        used_codes.add(auth_code)
        restaurant.auth_code = auth_code
        restaurant.save(update_fields=['auth_code'])


class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0012_alter_cashdesk_branch_alter_device_branch_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='auth_code',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
        migrations.RunPython(populate_restaurant_auth_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='restaurant',
            name='auth_code',
            field=models.CharField(default=generate_restaurant_auth_code, max_length=6, unique=True),
        ),
    ]
