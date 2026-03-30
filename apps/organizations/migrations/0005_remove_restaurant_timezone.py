from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0004_branch_service_fee_percent'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='restaurant',
            name='timezone',
        ),
    ]
