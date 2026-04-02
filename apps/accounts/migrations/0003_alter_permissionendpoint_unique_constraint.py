from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_initial'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='permissionendpoint',
            name='accounts_permission_endpoint_route_method_uniq',
        ),
        migrations.AddConstraint(
            model_name='permissionendpoint',
            constraint=models.UniqueConstraint(
                fields=('permission', 'url', 'method'),
                name='accounts_permission_endpoint_permission_route_method_uniq',
            ),
        ),
    ]
