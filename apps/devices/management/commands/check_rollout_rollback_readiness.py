from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import TvMonitorDevice
from apps.restaurants.models import Restaurant


REQUIRED_COMPATIBILITY_SCHEMA = {
    Restaurant._meta.db_table: {'auth_code'},
    TvMonitorDevice._meta.db_table: {'restaurant_auth_code_hash'},
    IntegrationConfig._meta.db_table: {'settings', 'settings_encrypted'},
    'local_agents_localagentenrollmenttoken': set(),
}


class Command(BaseCommand):
    help = 'Fail unless the release can still restore the pre-device-migration application.'

    def handle(self, *args, **options):
        table_names = set(connection.introspection.table_names())
        missing_objects = []

        with connection.cursor() as cursor:
            for table, required_columns in REQUIRED_COMPATIBILITY_SCHEMA.items():
                if table not in table_names:
                    missing_objects.append(f'table:{table}')
                    continue
                actual_columns = {
                    field.name
                    for field in connection.introspection.get_table_description(cursor, table)
                }
                missing_objects.extend(
                    f'column:{table}.{column}'
                    for column in sorted(required_columns - actual_columns)
                )

            if missing_objects:
                raise CommandError(
                    'Rollback compatibility schema is incomplete: '
                    + ', '.join(missing_objects)
                )

            integrations_table = connection.ops.quote_name(IntegrationConfig._meta.db_table)
            encrypted_column = connection.ops.quote_name('settings_encrypted')
            cursor.execute(
                f'SELECT COUNT(*) FROM {integrations_table} '
                f'WHERE {encrypted_column} IS NULL'
            )
            missing_ciphertext = cursor.fetchone()[0]

        if missing_ciphertext:
            raise CommandError(
                f'Encrypted integration settings backfill is incomplete: {missing_ciphertext} row(s).'
            )

        try:
            decrypted_count = 0
            for config in IntegrationConfig.objects.only('id', 'settings').iterator(chunk_size=200):
                # Attribute access invokes EncryptedJSONField decryption and
                # authentication without logging any credential value.
                config.settings
                decrypted_count += 1
        except (TypeError, ValueError) as error:
            raise CommandError(
                'At least one integration settings envelope cannot be decrypted '
                'with the configured INTEGRATION_FERNET_KEYS.'
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                'Rollback compatibility schema is present; '
                f'{decrypted_count} integration settings envelope(s) verified.'
            )
        )
