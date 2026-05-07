from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0004_cleanup_mock_and_qz_configs'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='integrationconfig',
            name='mode',
        ),
    ]
