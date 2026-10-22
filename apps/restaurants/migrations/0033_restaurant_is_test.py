from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('restaurants', '0032_hourly_service_fees_to_formulas')]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='is_test',
            field=models.BooleanField(
                default=False,
                help_text='Test branch: printer and fiscal hardware checks are advisory in monitoring.',
            ),
        ),
    ]
