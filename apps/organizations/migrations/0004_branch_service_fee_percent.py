from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0003_featureconfig_order_entry_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='service_fee_percent',
            field=models.PositiveIntegerField(default=10),
        ),
    ]
