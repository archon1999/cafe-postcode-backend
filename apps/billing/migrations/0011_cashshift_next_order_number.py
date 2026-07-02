from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0010_payment_breakdown_amounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashshift',
            name='next_order_number',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
