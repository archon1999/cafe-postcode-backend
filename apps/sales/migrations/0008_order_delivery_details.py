from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('sales', '0007_backfill_order_item_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_address',
            field=models.TextField(blank=True, default=''),
        ),
    ]
