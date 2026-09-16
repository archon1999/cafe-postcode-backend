from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('floor', '0007_hourly_service_fees')]

    operations = [
        migrations.AlterField(
            model_name='diningtable',
            name='table_number',
            field=models.CharField(max_length=255),
        ),
    ]
