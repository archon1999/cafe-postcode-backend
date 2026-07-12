import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('kitchen', '0003_kitchenticket_load_indexes'),
        ('printing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='kitchenticket',
            name='print_document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='kitchen_tickets',
                to='printing.printdocument',
            ),
        ),
    ]
