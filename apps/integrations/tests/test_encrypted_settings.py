from cryptography.fernet import Fernet
from django.db import connection
from django.test import TestCase, override_settings

from apps.integrations.api.admin.serializers.integration_config import IntegrationConfigSerializer
from apps.integrations.fields import ENCRYPTED_JSON_PREFIX
from apps.integrations.models import IntegrationConfig
from apps.restaurants.models import Restaurant


TEST_KEY = Fernet.generate_key().decode('ascii')


@override_settings(INTEGRATION_FERNET_KEYS=[TEST_KEY])
class EncryptedIntegrationSettingsTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Encrypted Config Cafe')

    def create_config(self, **settings):
        return IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='Secure Integration',
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            settings=settings,
        )

    def raw_settings(self, config):
        identifier = config.pk.hex if connection.vendor == 'sqlite' else str(config.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT settings_encrypted FROM integrations_integrationconfig WHERE id = %s',
                [identifier],
            )
            return cursor.fetchone()[0]

    def raw_rollback_settings(self, config):
        identifier = config.pk.hex if connection.vendor == 'sqlite' else str(config.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT settings FROM integrations_integrationconfig WHERE id = %s',
                [identifier],
            )
            return cursor.fetchone()[0]

    def test_settings_are_encrypted_at_rest_and_decrypted_for_internal_services(self):
        config = self.create_config(
            endpoint_url='http://192.168.1.20:8090',
            api_token='super-secret-token',
        )

        stored = str(self.raw_settings(config))
        self.assertIn(ENCRYPTED_JSON_PREFIX, stored)
        self.assertNotIn('super-secret-token', stored)
        self.assertNotIn('192.168.1.20', stored)

        loaded = IntegrationConfig.objects.get(pk=config.pk)
        self.assertEqual(loaded.settings['api_token'], 'super-secret-token')
        self.assertEqual(loaded.settings['endpoint_url'], 'http://192.168.1.20:8090')

    def test_new_writes_do_not_copy_secrets_to_retained_rollback_column(self):
        config = self.create_config(api_token='encrypted-only')

        stored = str(self.raw_settings(config))
        self.assertIn(ENCRYPTED_JSON_PREFIX, stored)
        self.assertNotIn('encrypted-only', stored)
        self.assertIsNone(self.raw_rollback_settings(config))

    def test_secondary_key_decrypts_and_save_rotates_to_primary_key(self):
        old_key = Fernet.generate_key().decode('ascii')
        new_key = Fernet.generate_key().decode('ascii')
        with override_settings(INTEGRATION_FERNET_KEYS=[old_key]):
            config = self.create_config(api_token='rotate-me')
            old_envelope = str(self.raw_settings(config))

        with override_settings(INTEGRATION_FERNET_KEYS=[new_key, old_key]):
            loaded = IntegrationConfig.objects.get(pk=config.pk)
            self.assertEqual(loaded.settings['api_token'], 'rotate-me')
            loaded.save(update_fields=['settings'])
            new_envelope = str(self.raw_settings(config))

        self.assertNotEqual(old_envelope, new_envelope)
        self.assertNotIn('rotate-me', new_envelope)

    def test_admin_output_masks_secrets_and_masked_patch_preserves_them(self):
        config = self.create_config(
            endpoint_url='http://192.168.1.20:8090',
            api_token='super-secret-token',
            nested={'clientSecret': 'nested-secret', 'label': 'terminal'},
        )

        output = IntegrationConfigSerializer(config).data
        self.assertEqual(output['settings']['api_token'], '********')
        self.assertEqual(output['settings']['nested']['clientSecret'], '********')
        self.assertEqual(output['settings']['nested']['label'], 'terminal')

        serializer = IntegrationConfigSerializer(
            config,
            data={
                'settings': {
                    'endpoint_url': 'http://192.168.1.21:8090',
                    'api_token': '********',
                    'nested': {'clientSecret': '********', 'label': 'renamed'},
                }
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.settings['api_token'], 'super-secret-token')
        self.assertEqual(updated.settings['nested']['clientSecret'], 'nested-secret')
        self.assertEqual(updated.settings['nested']['label'], 'renamed')

        omitted = IntegrationConfigSerializer(
            updated,
            data={'settings': {'endpoint_url': 'http://192.168.1.22:8090'}},
            partial=True,
        )
        self.assertTrue(omitted.is_valid(), omitted.errors)
        omitted_updated = omitted.save()
        self.assertEqual(omitted_updated.settings['api_token'], 'super-secret-token')

    def test_masked_secret_is_rejected_on_create(self):
        serializer = IntegrationConfigSerializer(
            data={
                'name': 'Invalid',
                'kind': IntegrationConfig.Kind.PAYMENT,
                'provider': 'marta-softpos',
                'settings': {'api_token': '********'},
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('settings', serializer.errors)

    def test_endpoint_credentials_query_and_fragment_are_rejected_and_legacy_output_is_masked(self):
        for endpoint in (
            'http://user:password@192.168.1.20:8090',
            'http://192.168.1.20:8090?token=secret',
            'http://192.168.1.20:8090#secret',
            'http://192.168.1.20:not-a-port',
        ):
            with self.subTest(endpoint=endpoint):
                serializer = IntegrationConfigSerializer(
                    data={
                        'name': 'Invalid endpoint',
                        'kind': IntegrationConfig.Kind.PAYMENT,
                        'provider': 'marta-softpos',
                        'settings': {'endpoint_url': endpoint},
                    }
                )
                self.assertFalse(serializer.is_valid())
                self.assertIn('settings', serializer.errors)

        legacy = self.create_config(
            endpoint_url='http://192.168.1.20:8090?token=legacy-secret'
        )
        output = IntegrationConfigSerializer(legacy).data
        self.assertEqual(output['settings']['endpoint_url'], '********')
        self.assertNotIn('legacy-secret', output['display_name'])
