from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0018_alter_fiscalshiftsession_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cashshift',
            name='expected_closing_cash_amount',
            field=models.IntegerField(default=0),
        ),
    ]
