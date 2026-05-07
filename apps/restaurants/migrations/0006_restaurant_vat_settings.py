from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0005_canonical_cashdesk_fiscal_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='vat_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='vat_percent',
            field=models.DecimalField(decimal_places=2, default=12, max_digits=5),
        ),
    ]
