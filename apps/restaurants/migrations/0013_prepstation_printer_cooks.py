from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0006_canonical_fiscal_drive_provider'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('restaurants', '0012_merge_unikassa_and_pos_auth_background'),
    ]

    operations = [
        migrations.AddField(
            model_name='prepstation',
            name='printer_integration',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='prep_stations',
                to='integrations.integrationconfig',
            ),
        ),
        migrations.AddField(
            model_name='prepstation',
            name='cooks',
            field=models.ManyToManyField(blank=True, related_name='prep_stations', to=settings.AUTH_USER_MODEL),
        ),
    ]
