from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('floor', '0005_diningtable_shape_variant_hall_grid_columns_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='hall',
            name='level',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
