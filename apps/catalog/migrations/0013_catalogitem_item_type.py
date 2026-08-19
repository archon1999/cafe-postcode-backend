from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0012_catalogitem_sale_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogitem',
            name='item_type',
            field=models.CharField(
                choices=[('product', 'Product'), ('service', 'Service')],
                default='product',
                max_length=16,
            ),
        ),
    ]
