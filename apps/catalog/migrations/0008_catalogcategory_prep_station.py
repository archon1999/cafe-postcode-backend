from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0007_backfill_marking_from_mxik_payload'),
        ('restaurants', '0013_prepstation_printer_cooks'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogcategory',
            name='prep_station',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='catalog_categories',
                to='restaurants.prepstation',
            ),
        ),
    ]
