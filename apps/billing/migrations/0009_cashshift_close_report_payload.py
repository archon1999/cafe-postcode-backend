from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_fiscalshiftsession'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashshift',
            name='close_report_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
