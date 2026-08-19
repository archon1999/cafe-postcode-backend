from django.db import migrations, models

import apps.integrations.fields


def copy_plaintext_to_encrypted_shadow(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    # Re-copy every row on retry. This repairs a partial prior run and also
    # closes a stale-shadow race if an old application process wrote the legacy
    # column before the documented configuration-write freeze took effect.
    queryset = IntegrationConfig.objects.only('pk', 'settings')
    for config in queryset.iterator(chunk_size=200):
        config.settings_encrypted = config.settings
        config.save(update_fields=['settings_encrypted'])


def validate_encrypted_shadow(apps, schema_editor):
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    for config in IntegrationConfig.objects.all().iterator(chunk_size=200):
        # Reading settings_encrypted proves that the configured key set can
        # decrypt every envelope. Equality also detects a concurrent old-code
        # write instead of silently switching the new release to stale config.
        if config.settings_encrypted != config.settings:
            raise RuntimeError(
                'Integration settings changed during encrypted backfill; '
                'freeze configuration writes and retry migration 0013.'
            )


def restore_plaintext_shadow_for_rollback(apps, schema_editor):
    """Decrypt every current value before the old ORM state is restored."""
    IntegrationConfig = apps.get_model('integrations', 'IntegrationConfig')
    table = schema_editor.quote_name(IntegrationConfig._meta.db_table)
    id_column = schema_editor.quote_name(IntegrationConfig._meta.pk.column)
    plaintext_column = schema_editor.quote_name('settings')
    connection = schema_editor.connection
    primary_key_field = IntegrationConfig._meta.pk

    with connection.cursor() as cursor:
        updates = []
        for config in IntegrationConfig.objects.all().iterator(chunk_size=200):
            updates.append(
                (
                    connection.ops.adapt_json_value(config.settings, None),
                    primary_key_field.get_db_prep_value(config.pk, connection),
                )
            )
            if len(updates) >= 200:
                cursor.executemany(
                    f'UPDATE {table} SET {plaintext_column} = %s WHERE {id_column} = %s',
                    updates,
                )
                updates = []
        if updates:
            cursor.executemany(
                f'UPDATE {table} SET {plaintext_column} = %s WHERE {id_column} = %s',
                updates,
            )


class Migration(migrations.Migration):
    # Each row is independently durable. If deployment is interrupted Django
    # reruns the idempotent full backfill instead of holding one long
    # transaction and a large WAL burst.
    atomic = False

    dependencies = [('integrations', '0012_cleanup_redundant_setup_integrations')]

    operations = [
        migrations.AddField(
            model_name='integrationconfig',
            name='settings_encrypted',
            field=apps.integrations.fields.EncryptedJSONField(blank=True, null=True),
        ),
        migrations.RunPython(
            copy_plaintext_to_encrypted_shadow,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            validate_encrypted_shadow,
            migrations.RunPython.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # New releases do not write the compatibility column. Nullable
                # keeps post-deploy IntegrationConfig inserts working while the
                # old plaintext values remain available for rollback.
                migrations.AlterField(
                    model_name='integrationconfig',
                    name='settings',
                    field=models.JSONField(blank=True, default=dict, null=True),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='integrationconfig',
                    name='settings',
                ),
                migrations.RenameField(
                    model_name='integrationconfig',
                    old_name='settings_encrypted',
                    new_name='settings',
                ),
                migrations.AlterField(
                    model_name='integrationconfig',
                    name='settings',
                    field=apps.integrations.fields.EncryptedJSONField(
                        blank=True,
                        db_column='settings_encrypted',
                        default=dict,
                    ),
                ),
            ],
        ),
        # Reverse order is deliberate: this executes before NOT NULL is put
        # back on the legacy column and before the encrypted column is removed.
        migrations.RunPython(
            migrations.RunPython.noop,
            restore_plaintext_shadow_for_rollback,
        ),
    ]
