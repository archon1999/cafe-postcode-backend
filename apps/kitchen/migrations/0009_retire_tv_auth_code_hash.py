import hashlib
import secrets
import string

from django.db import migrations, models


AUTH_CODE_ALPHABET = string.ascii_letters + string.digits


def restore_tv_hashes_for_rollback(apps, schema_editor):
    """Restore compatibility values for TVs created after the new release."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    TvMonitorDevice = apps.get_model('kitchen', 'TvMonitorDevice')
    restaurant_table = schema_editor.quote_name(Restaurant._meta.db_table)
    tv_table = schema_editor.quote_name(TvMonitorDevice._meta.db_table)
    auth_code_column = schema_editor.quote_name('auth_code')
    auth_hash_column = schema_editor.quote_name('restaurant_auth_code_hash')

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'SELECT {auth_code_column} FROM {restaurant_table} '
            f'WHERE {auth_code_column} IS NOT NULL'
        )
        used_codes = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            f'SELECT tv.id, tv.restaurant_id, restaurant.{auth_code_column} '
            f'FROM {tv_table} tv '
            f'JOIN {restaurant_table} restaurant ON restaurant.id = tv.restaurant_id '
            f'WHERE tv.{auth_hash_column} IS NULL'
        )
        rows = cursor.fetchall()
        for tv_id, restaurant_id, auth_code in rows:
            if auth_code is None:
                while True:
                    auth_code = ''.join(secrets.choice(AUTH_CODE_ALPHABET) for _ in range(6))
                    if auth_code not in used_codes:
                        used_codes.add(auth_code)
                        break
                cursor.execute(
                    f'UPDATE {restaurant_table} SET {auth_code_column} = %s WHERE id = %s',
                    [auth_code, restaurant_id],
                )
            cursor.execute(
                f'UPDATE {tv_table} SET {auth_hash_column} = %s WHERE id = %s',
                [hashlib.sha256(auth_code.encode('utf-8')).hexdigest(), tv_id],
            )


class Migration(migrations.Migration):
    dependencies = [
        ('kitchen', '0008_tv_monitor_device_binding'),
    ]

    operations = [
        # Preserve the legacy credential hash for a safe application rollback.
        # It is nullable so TVs created during the bounded migration window do
        # not fail against a column the new ORM no longer knows about.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name='tvmonitordevice',
                    name='restaurant_auth_code_hash',
                    field=models.CharField(max_length=64, null=True),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='tvmonitordevice',
                    name='restaurant_auth_code_hash',
                ),
            ],
        ),
        migrations.RunPython(migrations.RunPython.noop, restore_tv_hashes_for_rollback),
    ]
