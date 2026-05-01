from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0004_orderitem_load_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['restaurant', 'status', '-created_at'], name='order_open_checks_idx'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['restaurant', 'status', '-closed_at'], name='order_closed_checks_idx'),
        ),
    ]
