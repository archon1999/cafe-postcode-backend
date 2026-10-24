from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('platform', '0016_ai_usage_legacy_writer_defaults')]

    operations = [
        migrations.AddField(
            model_name='aiusagelog', name='usage_is_estimated',
            field=models.BooleanField(db_default=False, default=False, editable=False),
        ),
    ]
