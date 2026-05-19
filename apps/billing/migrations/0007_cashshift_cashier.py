from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_opened_by_to_cashier(apps, schema_editor):
    CashShift = apps.get_model('billing', 'CashShift')
    CashShift.objects.filter(cashier__isnull=True).update(cashier_id=models.F('opened_by_id'))


def clear_cashier(apps, schema_editor):
    CashShift = apps.get_model('billing', 'CashShift')
    CashShift.objects.update(cashier_id=None)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('billing', '0006_use_unikassa_receipt_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashshift',
            name='cashier',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cashier_cash_shifts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(copy_opened_by_to_cashier, clear_cashier),
    ]
