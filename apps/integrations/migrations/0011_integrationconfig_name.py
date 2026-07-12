from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('integrations', '0010_allow_multiple_integration_configs_per_provider')]

    operations = [
        migrations.AddField(
            model_name='integrationconfig',
            name='name',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
