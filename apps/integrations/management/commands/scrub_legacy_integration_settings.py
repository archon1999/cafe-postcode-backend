from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.integrations.models import IntegrationConfig


DEFAULT_BATCH_SIZE = 200
MAX_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        'Audit or NULL the retained plaintext IntegrationConfig.settings column '
        'after the encrypted release is healthy.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='NULL the legacy plaintext column after verifying every ciphertext envelope.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'Rows per UPDATE statement (1-{MAX_BATCH_SIZE}).',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
            raise CommandError(f'--batch-size must be between 1 and {MAX_BATCH_SIZE}.')

        with transaction.atomic():
            table = connection.ops.quote_name(IntegrationConfig._meta.db_table)
            id_column = connection.ops.quote_name(IntegrationConfig._meta.pk.column)
            plaintext_column = connection.ops.quote_name('settings')
            encrypted_column = connection.ops.quote_name('settings_encrypted')

            table_names = set(connection.introspection.table_names())
            if IntegrationConfig._meta.db_table not in table_names:
                raise CommandError('IntegrationConfig table does not exist.')
            with connection.cursor() as cursor:
                columns = {
                    field.name
                    for field in connection.introspection.get_table_description(
                        cursor,
                        IntegrationConfig._meta.db_table,
                    )
                }
                missing_columns = {'settings', 'settings_encrypted'} - columns
                if missing_columns:
                    raise CommandError(
                        'Integration settings compatibility columns are missing: '
                        + ', '.join(sorted(missing_columns))
                    )
                cursor.execute(
                    f'SELECT COUNT(*) FROM {table} WHERE {encrypted_column} IS NULL'
                )
                missing_ciphertext = cursor.fetchone()[0]
                cursor.execute(
                    f'SELECT COUNT(*) FROM {table} WHERE {plaintext_column} IS NOT NULL'
                )
                plaintext_count = cursor.fetchone()[0]

            if missing_ciphertext:
                raise CommandError(
                    f'Encrypted integration settings backfill is incomplete: '
                    f'{missing_ciphertext} row(s).'
                )

            queryset = IntegrationConfig.objects.only('id', 'settings').order_by('id')
            if options['apply']:
                queryset = queryset.select_for_update()

            prepared_ids = []
            primary_key_field = IntegrationConfig._meta.pk
            try:
                last_pk = None
                while True:
                    batch_queryset = queryset
                    if last_pk is not None:
                        batch_queryset = batch_queryset.filter(pk__gt=last_pk)
                    batch = list(batch_queryset[:batch_size])
                    if not batch:
                        break
                    for config in batch:
                        # Loading settings authenticates and decrypts the envelope.
                        # Retain only the prepared identifier, never the secret.
                        config.settings
                        prepared_ids.append(
                            primary_key_field.get_db_prep_value(config.pk, connection)
                        )
                    last_pk = batch[-1].pk
            except (TypeError, ValueError) as error:
                raise CommandError(
                    'At least one integration settings envelope cannot be decrypted '
                    'with the configured INTEGRATION_FERNET_KEYS.'
                ) from error

            if not options['apply']:
                self.stdout.write(
                    f'DRY-RUN: verified_envelopes={len(prepared_ids)} '
                    f'plaintext_rows={plaintext_count}'
                )
                self.stdout.write(
                    'Run again with --apply only after the new application passes '
                    'production smoke checks and the owner approves plaintext scrubbing.'
                )
                return

            scrubbed = 0
            with connection.cursor() as cursor:
                for offset in range(0, len(prepared_ids), batch_size):
                    batch = prepared_ids[offset : offset + batch_size]
                    placeholders = ', '.join(['%s'] * len(batch))
                    cursor.execute(
                        f'UPDATE {table} SET {plaintext_column} = NULL '
                        f'WHERE {plaintext_column} IS NOT NULL '
                        f'AND {id_column} IN ({placeholders})',
                        batch,
                    )
                    scrubbed += cursor.rowcount

            if scrubbed != plaintext_count:
                raise CommandError(
                    'Legacy plaintext settings changed during scrubbing; transaction rolled back.'
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'APPLIED: verified_envelopes={len(prepared_ids)} '
                f'scrubbed_plaintext_rows={scrubbed}'
            )
        )
