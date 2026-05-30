from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0006_canonical_fiscal_drive_provider'),
        ('restaurants', '0014_restaurant_service_fee_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashdesk',
            name='printer_integration',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='printer_cash_desks',
                to='integrations.integrationconfig',
            ),
        ),
    ]
