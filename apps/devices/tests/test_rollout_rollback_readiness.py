from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import Restaurant


class RolloutRollbackReadinessCommandTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Rollback readiness branch')
        self.config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='rollback-readiness',
            settings={'api_token': 'encrypted-secret'},
        )

    def test_command_accepts_complete_compatibility_schema_and_ciphertext(self):
        output = StringIO()

        call_command('check_rollout_rollback_readiness', stdout=output)

        self.assertIn('1 integration settings envelope(s) verified', output.getvalue())

    def test_command_rejects_incomplete_ciphertext_backfill(self):
        table = connection.ops.quote_name(IntegrationConfig._meta.db_table)
        encrypted_column = connection.ops.quote_name('settings_encrypted')
        id_column = connection.ops.quote_name(IntegrationConfig._meta.pk.column)
        prepared_pk = IntegrationConfig._meta.pk.get_db_prep_value(self.config.pk, connection)
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE {table} SET {encrypted_column} = NULL WHERE {id_column} = %s',
                [prepared_pk],
            )

        with self.assertRaisesMessage(CommandError, 'backfill is incomplete'):
            call_command('check_rollout_rollback_readiness')
