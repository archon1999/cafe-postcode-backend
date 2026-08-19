from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('printing', '0008_publish_separate_service_fee_rows'),
    ]

    operations = [
        migrations.AlterField(
            model_name='printdocument',
            name='idempotency_key',
            field=models.CharField(max_length=160),
        ),
        migrations.AlterField(
            model_name='printjob',
            name='idempotency_key',
            field=models.CharField(max_length=160),
        ),
    ]
