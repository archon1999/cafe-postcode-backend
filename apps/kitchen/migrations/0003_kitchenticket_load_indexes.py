from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kitchen', '0002_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='kitchenticket',
            index=models.Index(fields=['restaurant', 'status', 'created_at'], name='kt_rest_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='kitchenticket',
            index=models.Index(fields=['restaurant', 'status', 'completed_at'], name='kt_rest_status_done_idx'),
        ),
    ]
