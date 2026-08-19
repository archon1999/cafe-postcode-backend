import hashlib
import importlib
import uuid
from unittest import skipUnless

from django.apps import apps as django_apps
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.integrations.fields import ENCRYPTED_JSON_PREFIX
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import TvMonitorDevice
from apps.restaurants.models import Restaurant


restaurant_contract = importlib.import_module(
    'apps.restaurants.migrations.0025_remove_restaurant_auth_code'
)
tv_contract = importlib.import_module(
    'apps.kitchen.migrations.0009_retire_tv_auth_code_hash'
)
integration_contract = importlib.import_module(
    'apps.integrations.migrations.0013_encrypt_integration_settings'
)
local_agent_contract = importlib.import_module(
    'apps.local_agents.migrations.0006_remove_localagentenrollmenttoken'
)


class MigrationRollbackContractTests(TestCase):
    def setUp(self):
        self.schema_editor = connection.schema_editor()
        self.restaurant = Restaurant.objects.create(name='Rollback contract branch')

    @staticmethod
    def _prepared_pk(instance):
        return instance._meta.pk.get_db_prep_value(instance.pk, connection)

    def _column_names(self, table):
        with connection.cursor() as cursor:
            return {
                field.name
                for field in connection.introspection.get_table_description(cursor, table)
            }

    def test_retired_credentials_are_physically_retained_until_contract_cleanup(self):
        # The later max-length migration must advance Django's model state
        # without letting SQLite rebuild this table from state and silently
        # discard the intentionally hidden rollback credential column.
        self.assertEqual(
            Restaurant._meta.get_field('pos_auth_background_image').max_length,
            255,
        )
        self.assertIn('auth_code', self._column_names(Restaurant._meta.db_table))
        self.assertIn(
            'restaurant_auth_code_hash',
            self._column_names(TvMonitorDevice._meta.db_table),
        )
        self.assertIn(
            'local_agents_localagentenrollmenttoken',
            connection.introspection.table_names(),
        )

    def test_new_rows_work_and_reverse_hooks_restore_old_release_values(self):
        config = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='rollback-contract',
            settings={'api_token': 'rollback-secret'},
        )
        tv = TvMonitorDevice.objects.create(
            restaurant=self.restaurant,
            token_hash='f' * 64,
            paired_at=timezone.now(),
        )

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT auth_code FROM restaurants_restaurant WHERE id = %s',
                [self._prepared_pk(self.restaurant)],
            )
            self.assertIsNone(cursor.fetchone()[0])
            cursor.execute(
                'SELECT settings, settings_encrypted '
                'FROM integrations_integrationconfig WHERE id = %s',
                [self._prepared_pk(config)],
            )
            plaintext, encrypted = cursor.fetchone()
            self.assertIsNone(plaintext)
            self.assertIn(ENCRYPTED_JSON_PREFIX, str(encrypted))
            self.assertNotIn('rollback-secret', str(encrypted))
            cursor.execute(
                'SELECT restaurant_auth_code_hash '
                'FROM kitchen_tvmonitordevice WHERE id = %s',
                [self._prepared_pk(tv)],
            )
            self.assertIsNone(cursor.fetchone()[0])

        tv_contract.restore_tv_hashes_for_rollback(django_apps, self.schema_editor)
        integration_contract.restore_plaintext_shadow_for_rollback(
            django_apps,
            self.schema_editor,
        )
        restaurant_contract.restore_auth_codes_for_rollback(
            django_apps,
            self.schema_editor,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT auth_code FROM restaurants_restaurant WHERE id = %s',
                [self._prepared_pk(self.restaurant)],
            )
            auth_code = cursor.fetchone()[0]
            self.assertTrue(auth_code)
            cursor.execute(
                'SELECT restaurant_auth_code_hash '
                'FROM kitchen_tvmonitordevice WHERE id = %s',
                [self._prepared_pk(tv)],
            )
            self.assertEqual(
                cursor.fetchone()[0],
                hashlib.sha256(auth_code.encode('utf-8')).hexdigest(),
            )
            cursor.execute(
                'SELECT settings FROM integrations_integrationconfig WHERE id = %s',
                [self._prepared_pk(config)],
            )
            self.assertIn('rollback-secret', str(cursor.fetchone()[0]))


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL constraint contract')
class LegacyEnrollmentPostgresConstraintTests(TransactionTestCase):
    def setUp(self):
        self.schema_editor = connection.schema_editor()

    def _legacy_agent_foreign_keys(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor,
                local_agent_contract.LEGACY_TABLE,
            )
        return {
            tuple(details.get('columns') or ()): tuple(details['foreign_key'])
            for details in constraints.values()
            if details.get('foreign_key')
        }

    def test_hidden_legacy_agent_table_is_fk_detached_and_reversible(self):
        self.assertEqual(self._legacy_agent_foreign_keys(), {})

        with transaction.atomic():
            local_agent_contract.restore_legacy_enrollment_foreign_keys(
                django_apps,
                self.schema_editor,
            )
            self.assertEqual(
                self._legacy_agent_foreign_keys(),
                {
                    ('restaurant_id',): ('restaurants_restaurant', 'id'),
                    ('issued_by_id',): ('users_user', 'id'),
                },
            )
            local_agent_contract.detach_legacy_enrollment_foreign_keys(
                django_apps,
                self.schema_editor,
            )

        self.assertEqual(self._legacy_agent_foreign_keys(), {})

    def test_hidden_legacy_agent_fk_restore_fails_closed_on_orphans(self):
        orphan_id = uuid.uuid4()
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {local_agent_contract.LEGACY_TABLE} '
                '(id, created_at, updated_at, token_hash, expires_at, used_at, '
                'issued_by_id, restaurant_id) VALUES (%s, %s, %s, %s, %s, NULL, NULL, %s)',
                [orphan_id, now, now, 'e' * 64, now, uuid.uuid4()],
            )

        try:
            with self.assertRaisesRegex(RuntimeError, 'restaurant_id=1'):
                with transaction.atomic():
                    local_agent_contract.restore_legacy_enrollment_foreign_keys(
                        django_apps,
                        self.schema_editor,
                    )
            self.assertEqual(self._legacy_agent_foreign_keys(), {})
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM {local_agent_contract.LEGACY_TABLE} WHERE id = %s',
                    [orphan_id],
                )
