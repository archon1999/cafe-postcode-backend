from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0009_windows_raw_cyrillic_defaults'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='integrationconfig',
            unique_together=set(),
        ),
    ]
