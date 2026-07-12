from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def populate_session_security_fields(apps, schema_editor):
    AuthSession = apps.get_model('users', 'AuthSession')
    AuthSession.objects.filter(expires_at__isnull=True).update(
        surface='admin',
        expires_at=timezone.now() - timedelta(seconds=1),
    )


class Migration(migrations.Migration):
    dependencies = [('users', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='authsession',
            name='surface',
            field=models.CharField(blank=True, choices=[('admin', 'Admin'), ('pos', 'POS'), ('dashboard', 'Dashboard')], max_length=20),
        ),
        migrations.AddField(
            model_name='authsession',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(populate_session_security_fields, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='authsession',
            name='surface',
            field=models.CharField(choices=[('admin', 'Admin'), ('pos', 'POS'), ('dashboard', 'Dashboard')], max_length=20),
        ),
        migrations.AlterField(
            model_name='authsession',
            name='expires_at',
            field=models.DateTimeField(),
        ),
    ]
