from django.db import migrations, models


def backfill_payment_breakdowns(apps, schema_editor):
    Payment = apps.get_model('billing', 'Payment')
    for payment in Payment.objects.all().iterator():
        amount = int(payment.amount or 0)
        if payment.method == 'cash':
            cash_amount = amount
            card_amount = 0
        else:
            cash_amount = 0
            card_amount = amount
        payment.cash_amount = cash_amount
        payment.card_amount = card_amount
        payment.fiscal_cash_amount = cash_amount
        payment.fiscal_card_amount = card_amount
        payment.save(
            update_fields=[
                'cash_amount',
                'card_amount',
                'fiscal_cash_amount',
                'fiscal_card_amount',
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_cashshift_close_report_payload'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='cash_amount',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='payment',
            name='card_amount',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='payment',
            name='fiscal_cash_amount',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='payment',
            name='fiscal_card_amount',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='payment',
            name='fiscal_adjustment_reason',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.RunPython(backfill_payment_breakdowns, migrations.RunPython.noop),
    ]
