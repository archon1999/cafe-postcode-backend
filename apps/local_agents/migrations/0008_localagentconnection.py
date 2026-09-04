import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('local_agents', '0007_localagent_rollout_state'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocalAgentConnection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('connection_id', models.UUIDField(blank=True, null=True)),
                ('runtime_instance_id', models.CharField(blank=True, max_length=128)),
                ('version', models.CharField(blank=True, max_length=50)),
                ('protocol_version', models.PositiveSmallIntegerField(default=1)),
                ('identity_attested', models.BooleanField(default=False)),
                ('channel_name', models.CharField(blank=True, max_length=255)),
                ('connected', models.BooleanField(default=False)),
                ('connected_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('agent', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='connection_authority', to='local_agents.localagent')),
            ],
        ),
    ]
