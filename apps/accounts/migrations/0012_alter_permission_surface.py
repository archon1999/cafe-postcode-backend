from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0011_permission_action_permission_group_key_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='permission',
            name='surface',
            field=models.CharField(
                choices=[('admin', 'Admin'), ('pos', 'POS'), ('dashboard', 'Dashboard')],
                default='admin',
                max_length=20,
            ),
        ),
    ]
