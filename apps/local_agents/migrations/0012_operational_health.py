from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('local_agents', '0011_command_requested_by')]
    operations = [migrations.AddField(model_name='localagent', name='operational_health', field=models.JSONField(default=dict, blank=True))]
