from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0004_payment_load_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='register_fiscal',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='receipt',
            name='fiscal_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='receipt',
            name='fiscal_registered_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='receipt',
            name='original_paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='receipt',
            name='fiscal_error_code',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='receipt',
            name='fiscal_error_message',
            field=models.TextField(blank=True),
        ),
    ]
