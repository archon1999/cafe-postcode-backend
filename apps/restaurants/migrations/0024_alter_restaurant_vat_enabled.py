from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0023_restaurant_payment_total_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='restaurant',
            name='vat_enabled',
            field=models.BooleanField(default=True),
        ),
    ]
