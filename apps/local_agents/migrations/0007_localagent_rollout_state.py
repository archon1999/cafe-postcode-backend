from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('local_agents', '0006_remove_localagentenrollmenttoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='localagent',
            name='rollout_state',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
