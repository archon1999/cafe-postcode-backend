import apps.restaurants.models.restaurant
import common.storages
from django.db import migrations, models


class PreserveSQLiteCompatibilityAlterField(migrations.AlterField):
    """Avoid a SQLite table rebuild that would drop retained rollback columns."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'sqlite':
            return
        return super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'sqlite':
            return
        return super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0025_remove_restaurant_auth_code'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # SQLite does not enforce VARCHAR lengths, while AlterField
                # rebuilds the whole table and would discard the intentionally
                # state-hidden auth_code rollback column retained by 0025.
                PreserveSQLiteCompatibilityAlterField(
                    model_name='restaurant',
                    name='pos_auth_background_image',
                    field=models.ImageField(
                        blank=True,
                        max_length=255,
                        null=True,
                        storage=common.storages.RestaurantAuthBackgroundStorage,
                        upload_to=(
                            apps.restaurants.models.restaurant.restaurant_auth_background_upload_to
                        ),
                    ),
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name='restaurant',
                    name='pos_auth_background_image',
                    field=models.ImageField(
                        blank=True,
                        max_length=255,
                        null=True,
                        storage=common.storages.RestaurantAuthBackgroundStorage,
                        upload_to=(
                            apps.restaurants.models.restaurant.restaurant_auth_background_upload_to
                        ),
                    ),
                ),
            ],
        ),
    ]
