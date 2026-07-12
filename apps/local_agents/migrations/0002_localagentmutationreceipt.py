import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('local_agents', '0001_initial'),
        ('restaurants', '0012_merge_unikassa_and_pos_auth_background'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocalAgentMutationReceipt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('operation_id', models.CharField(max_length=128, unique=True)),
                ('user_id', models.UUIDField()),
                ('method', models.CharField(max_length=10)),
                ('path', models.CharField(max_length=500)),
                ('request_hash', models.CharField(max_length=64)),
                ('response_status', models.PositiveSmallIntegerField()),
                ('response_body', models.JSONField(blank=True, default=dict)),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='local_agent_mutation_receipts', to='restaurants.restaurant')),
            ],
            options={
                'ordering': ('created_at',),
                'indexes': [models.Index(fields=['restaurant', 'created_at'], name='agent_mut_rest_created_idx')],
            },
        ),
    ]
