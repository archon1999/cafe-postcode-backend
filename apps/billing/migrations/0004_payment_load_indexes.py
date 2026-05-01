from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['order', 'status'], name='payment_order_status_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['cash_shift', 'status'], name='payment_shift_status_idx'),
        ),
    ]
