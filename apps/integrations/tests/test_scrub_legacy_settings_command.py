import importlib
from io import StringIO

from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import Restaurant


encryption_migration = importlib.import_module(
    'apps.integrations.migrations.0013_encrypt_integration_settings'
)


class ScrubLegacyIntegrationSettingsCommandTests(TestCase):
    def setUp(self):
        restaurant = Restaurant.objects.create(name='Plaintext scrub branch')
        self.config = IntegrationConfig.objects.create(
            restaurant=restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='plaintext-scrub',
            settings={'api_token': 'legacy-plaintext-secret'},
        )
        self.table = connection.ops.quote_name(IntegrationConfig._meta.db_table)
        self.id_column = connection.ops.quote_name(IntegrationConfig._meta.pk.column)
        self.plaintext_column = connection.ops.quote_name('settings')
        self.encrypted_column = connection.ops.quote_name('settings_encrypted')
        self.prepared_pk = IntegrationConfig._meta.pk.get_db_prep_value(
            self.config.pk,
            connection,
        )
        self._write_raw_column(
            self.plaintext_column,
            connection.ops.adapt_json_value(
                {'api_token': 'legacy-plaintext-secret'},
                None,
            ),
        )

    def _write_raw_column(self, column, value):
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE {self.table} SET {column} = %s WHERE {self.id_column} = %s',
                [value, self.prepared_pk],
            )

    def _raw_plaintext(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT {self.plaintext_column} FROM {self.table} '
                f'WHERE {self.id_column} = %s',
                [self.prepared_pk],
            )
            return cursor.fetchone()[0]

    def test_dry_run_reports_without_scrubbing(self):
        output = StringIO()

        call_command('scrub_legacy_integration_settings', stdout=output)

        self.assertIn('DRY-RUN: verified_envelopes=1 plaintext_rows=1', output.getvalue())
        self.assertIn('legacy-plaintext-secret', str(self._raw_plaintext()))

    def test_apply_scrubs_plaintext_and_reverse_hook_can_restore_it(self):
        output = StringIO()

        call_command(
            'scrub_legacy_integration_settings',
            '--apply',
            '--batch-size=1',
            stdout=output,
        )

        self.assertIn('scrubbed_plaintext_rows=1', output.getvalue())
        self.assertIsNone(self._raw_plaintext())
        self.assertEqual(
            IntegrationConfig.objects.get(pk=self.config.pk).settings['api_token'],
            'legacy-plaintext-secret',
        )

        encryption_migration.restore_plaintext_shadow_for_rollback(
            django_apps,
            connection.schema_editor(),
        )
        self.assertIn('legacy-plaintext-secret', str(self._raw_plaintext()))

    def test_apply_rejects_missing_ciphertext_without_touching_plaintext(self):
        self._write_raw_column(self.encrypted_column, None)

        with self.assertRaisesMessage(CommandError, 'backfill is incomplete'):
            call_command('scrub_legacy_integration_settings', '--apply')

        self.assertIn('legacy-plaintext-secret', str(self._raw_plaintext()))

    def test_apply_rejects_undecryptable_ciphertext_without_touching_plaintext(self):
        self._write_raw_column(
            self.encrypted_column,
            connection.ops.adapt_json_value('enc:v1:not-a-valid-envelope', None),
        )

        with self.assertRaisesMessage(CommandError, 'cannot be decrypted'):
            call_command('scrub_legacy_integration_settings', '--apply')

        self.assertIn('legacy-plaintext-secret', str(self._raw_plaintext()))

    def test_invalid_batch_size_is_rejected(self):
        with self.assertRaisesMessage(CommandError, '--batch-size'):
            call_command('scrub_legacy_integration_settings', '--batch-size=0')
