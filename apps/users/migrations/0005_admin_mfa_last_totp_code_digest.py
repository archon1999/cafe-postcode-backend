from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0004_admin_refresh_mfa_security'),
    ]

    operations = [
        migrations.AddField(
            model_name='adminmfaprofile',
            name='last_totp_code_digest',
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
