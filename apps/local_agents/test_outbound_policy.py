from django.test import TestCase

from apps.devices.models import SecurityEvent
from apps.integrations.models import IntegrationConfig
from apps.local_agents.outbound_policy import (
    OutboundPolicyError,
    authorize_local_http_request,
    normalize_discovery_payload,
)
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService
from apps.restaurants.models import Restaurant


class LocalAgentOutboundPolicyTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Policy Restaurant')
        self.other_restaurant = Restaurant.objects.create(name='Other Restaurant')
        self.marta = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='MARTA',
            kind=IntegrationConfig.Kind.PAYMENT,
            provider='marta-softpos',
            settings={'endpoint_url': 'http://192.168.10.20:8090'},
        )
        self.fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='Fiscal Drive',
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'endpoint_url': 'http://127.0.0.1:3449'},
        )

    def authorize(self, **overrides):
        values = {
            'restaurant': self.restaurant,
            'purpose': 'marta',
            'method': 'GET',
            'url': 'http://192.168.10.20:8090/health',
            'timeout_seconds': 10,
        }
        values.update(overrides)
        return authorize_local_http_request(**values)

    def test_exact_restaurant_integration_is_authorized_and_bound_to_id(self):
        result = self.authorize()

        self.assertEqual(result.integration_id, str(self.marta.id))
        self.assertEqual(result.purpose, 'marta')
        self.assertEqual(result.url, 'http://192.168.10.20:8090/health')

    def test_cross_tenant_or_unconfigured_target_is_denied(self):
        with self.assertRaises(OutboundPolicyError):
            self.authorize(restaurant=self.other_restaurant)
        with self.assertRaises(OutboundPolicyError):
            self.authorize(url='http://192.168.10.21:8090/health')
        with self.assertRaises(OutboundPolicyError):
            self.authorize(integration_id=self.fiscal.id)

    def test_metadata_public_loopback_and_unsafe_url_components_are_denied(self):
        bad_urls = (
            'http://169.254.169.254:8090/health',
            'http://8.8.8.8:8090/health',
            'http://127.0.0.1:8090/health',
            'http://user:password@192.168.10.20:8090/health',
            'http://192.168.10.20:8090/health#secret',
            'http://192.168.10.20:22/health',
            'https://192.168.10.20:8090/health',
        )
        for value in bad_urls:
            with self.subTest(value=value), self.assertRaises(OutboundPolicyError):
                self.authorize(url=value)

    def test_purpose_restricts_method_path_timeout_and_body(self):
        cases = (
            {'method': 'POST'},
            {'url': 'http://192.168.10.20:8090/admin'},
            {'url': 'http://192.168.10.20:8090/%2e%2e/admin'},
            {'url': 'http://192.168.10.20:8090/%252e%252e/admin'},
            {'url': 'http://192.168.10.20:8090/health?token=secret'},
            {'timeout_seconds': 31},
            {'json_body': {'blob': 'x' * (128 * 1024)}},
            {'form_body': {'blob': '?' * (64 * 1024)}},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(OutboundPolicyError):
                self.authorize(**values)

    def test_loopback_exception_is_narrowly_scoped_to_fiscal_provider(self):
        result = self.authorize(
            purpose='fiscal-drive',
            method='POST',
            url='http://127.0.0.1:3449/FiscalDrive/List',
            integration_id=self.fiscal.id,
        )
        self.assertEqual(result.integration_id, str(self.fiscal.id))

        with self.assertRaises(OutboundPolicyError):
            self.authorize(
                purpose='fiscal-drive',
                method='GET',
                url='http://127.0.0.1:3449/FiscalDrive/List',
                integration_id=self.fiscal.id,
            )

    def test_discovery_cannot_be_repurposed_as_a_port_scanner(self):
        self.assertEqual(
            normalize_discovery_payload('marta.discover', {}),
            {'port': 8090, 'timeoutMillis': 900, 'maxConcurrency': 96},
        )
        with self.assertRaises(OutboundPolicyError):
            normalize_discovery_payload('marta.discover', {'port': 22})
        with self.assertRaises(OutboundPolicyError):
            normalize_discovery_payload('unikassa.discover', {'pathPrefix': '/admin'})
        with self.assertRaises(OutboundPolicyError):
            normalize_discovery_payload('unikassa.discover', {'maxConcurrency': 1000})

    def test_direct_generic_command_cannot_bypass_policy_helper(self):
        with self.assertRaises(LocalAgentCommandError) as raised:
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='local_http.request',
                payload={
                    'method': 'GET',
                    'url': 'http://192.168.10.20:8090/health',
                    'timeoutSeconds': 10,
                },
            )
        self.assertEqual(raised.exception.code, 'LOCAL_HTTP_POLICY_DENIED')
        event = SecurityEvent.objects.get(event_type='LOCAL_AGENT_TARGET_DENIED')
        self.assertEqual(event.restaurant, self.restaurant)
        self.assertEqual(event.result, 'DENIED')
        self.assertEqual(event.metadata['reason'], 'purpose_denied')
        self.assertNotIn('url', event.metadata)
        self.assertNotIn('192.168.10.20', str(event.metadata))

    def test_marta_operational_query_is_allowlisted_but_duplicate_or_secret_key_is_not(self):
        result = self.authorize(
            url=(
                'http://192.168.10.20:8090/transaction'
                '?type=PURCHASE&amount=100&pid=1&tin=307678400'
            )
        )
        self.assertIn('type=PURCHASE', result.url)

        for url in (
            'http://192.168.10.20:8090/transaction?pid=1&pid=2',
            'http://192.168.10.20:8090/transaction?token=secret',
        ):
            with self.subTest(url=url), self.assertRaises(OutboundPolicyError):
                self.authorize(url=url)
