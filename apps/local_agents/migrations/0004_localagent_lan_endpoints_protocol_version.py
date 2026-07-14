from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('local_agents', '0003_localagentenrollmenttoken')]

    operations = [
        migrations.AddField(
            model_name='localagent',
            name='lan_endpoints',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='localagent',
            name='protocol_version',
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
