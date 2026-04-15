from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0002_restaurant_faktura_payload'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Device',
        ),
    ]
