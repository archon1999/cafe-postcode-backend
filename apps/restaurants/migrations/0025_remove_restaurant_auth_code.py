import secrets
import string

from django.db import migrations, models

import apps.restaurants.models.restaurant


AUTH_CODE_ALPHABET = string.ascii_letters + string.digits


def restore_auth_codes_for_rollback(apps, schema_editor):
    """Make the retained compatibility column valid before old code is restored."""
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    table = schema_editor.quote_name(Restaurant._meta.db_table)
    id_column = schema_editor.quote_name(Restaurant._meta.pk.column)
    auth_code_column = schema_editor.quote_name('auth_code')

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'SELECT {auth_code_column} FROM {table} WHERE {auth_code_column} IS NOT NULL')
        used_codes = {row[0] for row in cursor.fetchall()}
        cursor.execute(f'SELECT {id_column} FROM {table} WHERE {auth_code_column} IS NULL')
        missing_ids = [row[0] for row in cursor.fetchall()]

        updates = []
        for restaurant_id in missing_ids:
            while True:
                auth_code = ''.join(secrets.choice(AUTH_CODE_ALPHABET) for _ in range(6))
                if auth_code not in used_codes:
                    used_codes.add(auth_code)
                    updates.append((auth_code, restaurant_id))
                    break
        if updates:
            cursor.executemany(
                f'UPDATE {table} SET {auth_code_column} = %s WHERE {id_column} = %s',
                updates,
            )


class Migration(migrations.Migration):
    dependencies = [
        ('restaurants', '0024_alter_restaurant_vat_enabled'),
    ]

    operations = [
        # Keep the physical column through the rollback window. New application
        # code no longer supplies a value, so only relax NOT NULL. The model
        # state forgets the credential immediately, while an old release can be
        # restored without recovering deleted data.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name='restaurant',
                    name='auth_code',
                    field=models.CharField(
                        default=apps.restaurants.models.restaurant.generate_restaurant_auth_code,
                        max_length=6,
                        null=True,
                        unique=True,
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='restaurant',
                    name='auth_code',
                ),
            ],
        ),
        # On reverse this runs before NOT NULL is restored, covering restaurants
        # created by the new release during the rollback window.
        migrations.RunPython(migrations.RunPython.noop, restore_auth_codes_for_rollback),
    ]
