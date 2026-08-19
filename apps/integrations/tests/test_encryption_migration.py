from cryptography.fernet import Fernet
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

from apps.integrations.fields import ENCRYPTED_JSON_PREFIX


TEST_KEY = Fernet.generate_key().decode('ascii')


@override_settings(INTEGRATION_FERNET_KEYS=[TEST_KEY])
class EncryptedSettingsMigrationTests(TransactionTestCase):
    migrate_from = [
        ('integrations', '0012_cleanup_redundant_setup_integrations'),
        ('restaurants', '0024_alter_restaurant_vat_enabled'),
    ]
    migrate_to = [
        ('integrations', '0013_encrypt_integration_settings'),
        ('restaurants', '0025_remove_restaurant_auth_code'),
    ]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        Restaurant = old_apps.get_model('restaurants', 'Restaurant')
        IntegrationConfig = old_apps.get_model('integrations', 'IntegrationConfig')
        restaurant = Restaurant.objects.create(name='Encryption migration branch')
        self.restaurant_id = restaurant.pk
        config = IntegrationConfig.objects.create(
            restaurant=restaurant,
            kind='payment',
            provider='pre-migration',
            settings={'api_token': 'pre-migration-secret'},
        )
        self.config_id = config.pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    @staticmethod
    def _prepared_pk(model, value):
        return model._meta.pk.get_db_prep_value(value, connection)

    def test_forward_shadow_backfill_and_reverse_cover_post_release_rows(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        Restaurant = new_apps.get_model('restaurants', 'Restaurant')
        IntegrationConfig = new_apps.get_model('integrations', 'IntegrationConfig')

        migrated = IntegrationConfig.objects.get(pk=self.config_id)
        self.assertEqual(migrated.settings['api_token'], 'pre-migration-secret')
        post_release = IntegrationConfig.objects.create(
            restaurant=Restaurant.objects.get(pk=self.restaurant_id),
            kind='payment',
            provider='post-migration',
            settings={'api_token': 'post-migration-secret'},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT settings, settings_encrypted '
                'FROM integrations_integrationconfig WHERE id = %s',
                [self._prepared_pk(IntegrationConfig, self.config_id)],
            )
            retained_plaintext, encrypted = cursor.fetchone()
            self.assertIn('pre-migration-secret', str(retained_plaintext))
            self.assertIn(ENCRYPTED_JSON_PREFIX, str(encrypted))
            self.assertNotIn('pre-migration-secret', str(encrypted))
            cursor.execute(
                'SELECT settings FROM integrations_integrationconfig WHERE id = %s',
                [self._prepared_pk(IntegrationConfig, post_release.pk)],
            )
            self.assertIsNone(cursor.fetchone()[0])

        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        OldIntegrationConfig = old_apps.get_model('integrations', 'IntegrationConfig')
        self.assertEqual(
            OldIntegrationConfig.objects.get(pk=self.config_id).settings['api_token'],
            'pre-migration-secret',
        )
        self.assertEqual(
            OldIntegrationConfig.objects.get(pk=post_release.pk).settings['api_token'],
            'post-migration-secret',
        )
