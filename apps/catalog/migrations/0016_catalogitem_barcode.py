from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalog', '0015_alter_catalogitem_sale_unit')]

    operations = [
        migrations.AddField(
            model_name='catalogitem',
            name='barcode',
            field=models.CharField(blank=True, db_index=True, default='', max_length=14),
        ),
    ]
