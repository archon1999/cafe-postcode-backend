from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


def normalize_service_fee_percentages(apps, schema_editor):
    for model_name in ('Hall', 'DiningTable'):
        model = apps.get_model('floor', model_name)
        for row in model.objects.all().only('id', 'service_fee_percent').iterator():
            normalized = Decimal(str(row.service_fee_percent or 0)).quantize(
                Decimal('1'),
                rounding=ROUND_HALF_UP,
            )
            model.objects.filter(pk=row.pk).update(service_fee_percent=int(normalized))


class Migration(migrations.Migration):
    dependencies = [
        ('floor', '0004_diningtable_service_fee_enabled_and_more'),
    ]

    operations = [
        migrations.RunPython(normalize_service_fee_percentages, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='hall',
            name='service_fee_percent',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='diningtable',
            name='service_fee_percent',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
