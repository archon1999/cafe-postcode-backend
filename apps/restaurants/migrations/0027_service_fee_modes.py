from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("restaurants", "0026_expand_pos_auth_background_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="service_fee_mode",
            field=models.CharField(
                choices=[("percentage", "Percentage"), ("hourly", "Hourly")],
                default="percentage",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="service_fee_hourly_rate",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
