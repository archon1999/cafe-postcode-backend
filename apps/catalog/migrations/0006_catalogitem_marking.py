from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0005_catalogcategory_cash_payment_forbidden'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogitem',
            name='requires_marking',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='catalogitem',
            name='marking_gtin',
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
    ]
