from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0016_cashdesk_mixed_payment_methods'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='social',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
