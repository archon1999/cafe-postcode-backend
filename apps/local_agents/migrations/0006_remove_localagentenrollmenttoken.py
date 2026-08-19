from django.db import migrations


LEGACY_TABLE = 'local_agents_localagentenrollmenttoken'
LEGACY_FOREIGN_KEYS = (
    (
        'local_agents_localag_restaurant_id_a3a4c1bd_fk_restauran',
        'restaurant_id',
        'restaurants_restaurant',
        'id',
    ),
    (
        'local_agents_localag_issued_by_id_c23d293d_fk_users_use',
        'issued_by_id',
        'users_user',
        'id',
    ),
)


def _postgres_foreign_keys(schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        return {}

    with connection.cursor() as cursor:
        if LEGACY_TABLE not in connection.introspection.table_names(cursor):
            raise RuntimeError(f'Required rollback table {LEGACY_TABLE!r} is missing.')
        constraints = connection.introspection.get_constraints(cursor, LEGACY_TABLE)

    return {
        name: details
        for name, details in constraints.items()
        if details.get('foreign_key')
    }


def detach_legacy_enrollment_foreign_keys(apps, schema_editor):
    """Detach hidden-table FKs while retaining every rollback row and index."""
    foreign_keys = _postgres_foreign_keys(schema_editor)
    if schema_editor.connection.vendor != 'postgresql':
        return

    quote = schema_editor.quote_name
    expected_columns = {column for _, column, _, _ in LEGACY_FOREIGN_KEYS}
    actual_by_column = {
        tuple(details.get('columns') or ()): name
        for name, details in foreign_keys.items()
    }
    missing_columns = sorted(
        column for column in expected_columns if (column,) not in actual_by_column
    )
    if missing_columns:
        raise RuntimeError(
            'Cannot detach legacy enrollment foreign keys; missing column constraint(s): '
            + ', '.join(missing_columns)
        )

    for column in sorted(expected_columns):
        constraint_name = actual_by_column[(column,)]
        schema_editor.execute(
            f'ALTER TABLE {quote(LEGACY_TABLE)} '
            f'DROP CONSTRAINT {quote(constraint_name)}'
        )


def restore_legacy_enrollment_foreign_keys(apps, schema_editor):
    """Restore and validate old-release FKs, failing closed on orphaned rows."""
    existing = _postgres_foreign_keys(schema_editor)
    if schema_editor.connection.vendor != 'postgresql':
        return

    quote = schema_editor.quote_name
    existing_by_column = {
        tuple(details.get('columns') or ()): (name, details)
        for name, details in existing.items()
    }

    for constraint_name, column, target_table, target_column in LEGACY_FOREIGN_KEYS:
        current = existing_by_column.get((column,))
        if current:
            _, details = current
            expected_target = (target_table, target_column)
            if tuple(details.get('foreign_key') or ()) != expected_target:
                raise RuntimeError(
                    f'Unexpected legacy enrollment foreign key target for {column!r}.'
                )
            continue

        schema_editor.execute(
            f'ALTER TABLE {quote(LEGACY_TABLE)} '
            f'ADD CONSTRAINT {quote(constraint_name)} '
            f'FOREIGN KEY ({quote(column)}) '
            f'REFERENCES {quote(target_table)} ({quote(target_column)}) '
            'DEFERRABLE INITIALLY DEFERRED NOT VALID'
        )

    orphan_counts = []
    with schema_editor.connection.cursor() as cursor:
        for _, column, target_table, target_column in LEGACY_FOREIGN_KEYS:
            nullable_filter = f'legacy.{quote(column)} IS NOT NULL AND '
            cursor.execute(
                f'SELECT COUNT(*) FROM {quote(LEGACY_TABLE)} AS legacy '
                f'LEFT JOIN {quote(target_table)} AS target '
                f'ON legacy.{quote(column)} = target.{quote(target_column)} '
                f'WHERE {nullable_filter}target.{quote(target_column)} IS NULL'
            )
            orphan_counts.append((column, cursor.fetchone()[0]))

    orphaned = [(column, count) for column, count in orphan_counts if count]
    if orphaned:
        summary = ', '.join(f'{column}={count}' for column, count in orphaned)
        raise RuntimeError(
            'Cannot restore legacy enrollment foreign keys while orphaned rows exist: '
            + summary
        )

    refreshed = _postgres_foreign_keys(schema_editor)
    refreshed_by_column = {
        tuple(details.get('columns') or ()): name
        for name, details in refreshed.items()
    }
    for _, column, _, _ in LEGACY_FOREIGN_KEYS:
        constraint_name = refreshed_by_column.get((column,))
        if not constraint_name:
            raise RuntimeError(
                f'Legacy enrollment foreign key for {column!r} was not created.'
            )
        schema_editor.execute(
            f'ALTER TABLE {quote(LEGACY_TABLE)} '
            f'VALIDATE CONSTRAINT {quote(constraint_name)}'
        )


class Migration(migrations.Migration):
    dependencies = [
        ('local_agents', '0005_localagent_credential_migrated_at_localagent_device'),
    ]

    operations = [
        # Contract the Django state now, but retain the physical table until the
        # device migration has completed and the rollback window has elapsed.
        # Reversing this migration therefore makes the old model usable again
        # without trying to reconstruct deleted enrollment records.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    detach_legacy_enrollment_foreign_keys,
                    restore_legacy_enrollment_foreign_keys,
                ),
            ],
            state_operations=[
                migrations.DeleteModel(
                    name='LocalAgentEnrollmentToken',
                ),
            ],
        ),
    ]
