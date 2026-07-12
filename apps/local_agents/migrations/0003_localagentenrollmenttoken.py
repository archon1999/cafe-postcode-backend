import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('local_agents', '0002_localagentmutationreceipt'),
        ('restaurants', '0020_remove_unikassa_provider'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocalAgentEnrollmentToken',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('issued_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='issued_local_agent_enrollment_tokens', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='local_agent_enrollment_tokens', to='restaurants.restaurant')),
            ],
            options={
                'ordering': ('-created_at',),
                'indexes': [models.Index(fields=['restaurant', 'expires_at'], name='agent_enroll_rest_exp_idx')],
            },
        ),
    ]
