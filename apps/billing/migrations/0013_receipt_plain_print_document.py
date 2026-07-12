import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('printing', '0001_initial'),
        ('billing', '0012_convert_failed_fiscal_receipts_to_plain_payments'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='print_document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='receipts',
                to='printing.printdocument',
            ),
        ),
        migrations.AlterField(
            model_name='receipt',
            name='kind',
            field=models.CharField(
                choices=[
                    ('plain', 'Plain payment receipt'),
                    ('fiscal', 'Fiscal'),
                    ('refund', 'Refund'),
                ],
                default='fiscal',
                max_length=20,
            ),
        ),
    ]
