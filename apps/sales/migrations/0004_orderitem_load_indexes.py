from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_order_display_name'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='orderitem',
            index=models.Index(fields=['order', 'status'], name='orderitem_order_status_idx'),
        ),
        migrations.AddIndex(
            model_name='orderitem',
            index=models.Index(fields=['prep_station', 'status'], name='orderitem_station_status_idx'),
        ),
    ]
