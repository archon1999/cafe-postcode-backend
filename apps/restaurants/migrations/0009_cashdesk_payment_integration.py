from django.db import migrations, models
import django.db.models.deletion


def assign_existing_marta_configs(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')

    restaurant_ids = CashDesk.objects.values_list('restaurant_id', flat=True).distinct()
    for restaurant_id in restaurant_ids:
        config = (
            IntegrationConfig.objects.filter(
                restaurant_id=restaurant_id,
                kind='payment',
                provider='marta-softpos',
                is_enabled=True,
            )
            .order_by('-created_at')
            .first()
        )
        if config is None:
            continue
        CashDesk.objects.filter(
            restaurant_id=restaurant_id,
            payment_integration__isnull=True,
        ).update(payment_integration_id=config.id)


def unassign_marta_configs(apps, schema_editor):
    CashDesk = apps.get_model('restaurants', 'CashDesk')
    CashDesk.objects.filter(payment_integration__provider='marta-softpos').update(payment_integration_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0006_canonical_fiscal_drive_provider'),
        ('restaurants', '0008_cashdesk_fiscal_integration'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashdesk',
            name='payment_integration',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='payment_cash_desks',
                to='integrations.integrationconfig',
            ),
        ),
        migrations.RunPython(assign_existing_marta_configs, unassign_marta_configs),
    ]
