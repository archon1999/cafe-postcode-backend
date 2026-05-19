from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0006_canonical_fiscal_drive_provider'),
        ('restaurants', '0007_cashdesk_unikassa_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashdesk',
            name='fiscal_integration',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cash_desks',
                to='integrations.integrationconfig',
            ),
        ),
    ]
