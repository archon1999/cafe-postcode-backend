from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0004_catalogcategory_image_file_catalogitem_image_file_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogcategory',
            name='cash_payment_forbidden',
            field=models.BooleanField(default=False),
        ),
    ]
