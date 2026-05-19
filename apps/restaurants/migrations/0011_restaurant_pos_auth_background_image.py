from django.db import migrations, models

import apps.restaurants.models.restaurant
import common.storages


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0010_use_unikassa_fiscal_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='pos_auth_background_image',
            field=models.ImageField(
                blank=True,
                null=True,
                storage=common.storages.RestaurantAuthBackgroundStorage,
                upload_to=apps.restaurants.models.restaurant.restaurant_auth_background_upload_to,
            ),
        ),
    ]
