import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('restaurants', '0012_merge_unikassa_and_pos_auth_background'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocalAgent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, max_length=255)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('status', models.CharField(choices=[('offline', 'Offline'), ('online', 'Online')], default='offline', max_length=20)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('version', models.CharField(blank=True, max_length=50)),
                ('capabilities', models.JSONField(blank=True, default=list)),
                ('is_active', models.BooleanField(default=True)),
                ('restaurant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='local_agent', to='restaurants.restaurant')),
            ],
            options={
                'ordering': ('restaurant__name',),
            },
        ),
        migrations.CreateModel(
            name='LocalAgentCommand',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('command_type', models.CharField(max_length=80)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('timed_out', 'Timed out')], default='pending', max_length=20)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('result', models.JSONField(blank=True, default=dict)),
                ('error', models.JSONField(blank=True, default=dict)),
                ('timeout_seconds', models.PositiveIntegerField(default=30)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='commands', to='local_agents.localagent')),
            ],
            options={
                'ordering': ('-created_at',),
                'indexes': [
                    models.Index(fields=['agent', 'status'], name='local_agent_agent_i_3c3563_idx'),
                    models.Index(fields=['created_at'], name='local_agent_created_601553_idx'),
                ],
            },
        ),
    ]
