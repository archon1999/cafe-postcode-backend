from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0013_catalogitem_item_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogitem',
            name='archived_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
