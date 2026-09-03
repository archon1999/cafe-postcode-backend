from django.db import migrations


def restore_physical_auth_code_column(apps, schema_editor):
    """Restore the state-hidden credential column if a table rebuild dropped it.

    Migration 0025 intentionally retained this nullable column for safe rollback.
    Later SQLite table rebuilds only know Django's model state, so they can drop
    the hidden column. Keep the repair idempotent for databases where it remains.
    """

    Restaurant = apps.get_model("restaurants", "Restaurant")
    table_name = Restaurant._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }
    if "auth_code" in columns:
        return

    quoted_table = schema_editor.quote_name(table_name)
    quoted_column = schema_editor.quote_name("auth_code")
    schema_editor.execute(
        f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} varchar(6) NULL"
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("restaurants", "0027_service_fee_modes"),
    ]

    operations = [
        # Keep this database-only. Current application state must continue to
        # hide auth_code; reverse migration 0025 will populate and constrain it.
        migrations.RunPython(
            restore_physical_auth_code_column,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
