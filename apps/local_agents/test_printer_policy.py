import base64

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from apps.devices.models import SecurityEvent
from apps.integrations.api.admin.serializers import IntegrationConfigSerializer
from apps.integrations.models import IntegrationConfig
from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.printer_policy import (
    MAX_RAW_PAYLOAD_BYTES,
    PrinterPolicyError,
    authorize_printer_command,
)
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService
from apps.restaurants.models import Restaurant
from apps.users.services import AdminAuthService


User = get_user_model()


class PrinterPolicyTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Printer Policy Restaurant')
        self.other_restaurant = Restaurant.objects.create(name='Other Printer Restaurant')
        self.printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='Receipt printer',
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'socket',
                'host': 'Printer.LAN.',
                'port': 9100,
            },
        )

    def test_exact_enabled_restaurant_printer_is_canonicalized(self):
        result = authorize_printer_command(
            restaurant=self.restaurant,
            command_type='printer.check',
            payload={
                'connectionType': 'socket',
                'host': 'PRINTER.LAN',
                'port': 9100,
            },
        )

        self.assertEqual(result['integrationId'], str(self.printer.id))
        self.assertEqual(result['host'], 'printer.lan')
        self.assertEqual(result['port'], 9100)

    def test_cross_tenant_mismatch_disabled_and_arbitrary_port_are_denied(self):
        cases = (
            {
                'restaurant': self.other_restaurant,
                'payload': {'integrationId': str(self.printer.id)},
            },
            {
                'restaurant': self.restaurant,
                'payload': {'integrationId': str(self.printer.id), 'host': '192.168.1.99'},
            },
            {
                'restaurant': self.restaurant,
                'payload': {'integrationId': str(self.printer.id), 'port': 22},
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(PrinterPolicyError):
                authorize_printer_command(
                    restaurant=case['restaurant'],
                    command_type='printer.check',
                    payload=case['payload'],
                )

        self.printer.is_enabled = False
        self.printer.save(update_fields=['is_enabled', 'updated_at'])
        with self.assertRaises(PrinterPolicyError):
            authorize_printer_command(
                restaurant=self.restaurant,
                command_type='printer.check',
                payload={'integrationId': str(self.printer.id)},
            )

    def test_public_metadata_loopback_and_non_9100_configurations_are_denied(self):
        for host, port in (
            ('127.0.0.1', 9100),
            ('169.254.169.254', 9100),
            ('8.8.8.8', 9100),
            ('metadata.google.internal', 9100),
            ('192.168.1.50', 22),
        ):
            with self.subTest(host=host, port=port):
                self.printer.settings = {
                    'connection_type': 'socket',
                    'host': host,
                    'port': port,
                }
                self.printer.save(update_fields=['settings', 'updated_at'])
                with self.assertRaises(PrinterPolicyError):
                    authorize_printer_command(
                        restaurant=self.restaurant,
                        command_type='printer.check',
                        payload={'integrationId': str(self.printer.id)},
                    )

    def test_raw_body_is_validated_and_capped(self):
        valid = base64.b64encode(b'receipt').decode()
        result = authorize_printer_command(
            restaurant=self.restaurant,
            command_type='printer.raw',
            payload={'integrationId': str(self.printer.id), 'payloadBase64': valid},
        )
        self.assertEqual(result['payloadBase64'], valid)

        too_large = base64.b64encode(b'x' * (MAX_RAW_PAYLOAD_BYTES + 1)).decode()
        for encoded in ('not base64!', too_large):
            with self.subTest(size=len(encoded)), self.assertRaises(PrinterPolicyError):
                authorize_printer_command(
                    restaurant=self.restaurant,
                    command_type='printer.raw',
                    payload={'integrationId': str(self.printer.id), 'payloadBase64': encoded},
                )

    def test_remote_system_printer_names_are_denied(self):
        self.printer.settings = {
            'connection_type': 'system_printer',
            'printer_name': r'\\server\receipt',
        }
        self.printer.save(update_fields=['settings', 'updated_at'])
        with self.assertRaises(PrinterPolicyError):
            authorize_printer_command(
                restaurant=self.restaurant,
                command_type='printer.check',
                payload={'integrationId': str(self.printer.id)},
            )

    def test_admin_serializer_rejects_remote_spooler_and_arbitrary_raw_port(self):
        for settings in (
            {'connection_type': 'system_printer', 'printer_name': r'\\server\receipt'},
            {'connection_type': 'socket', 'host': '192.168.1.50', 'port': 22},
        ):
            serializer = IntegrationConfigSerializer(
                data={
                    'kind': IntegrationConfig.Kind.PRINTER,
                    'provider': 'windows-raw',
                    'is_enabled': True,
                    'settings': settings,
                }
            )
            with self.subTest(settings=settings):
                self.assertFalse(serializer.is_valid())


class PrinterCommandServicePolicyTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Printer Command Restaurant')
        self.agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])
        self.printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'connection_type': 'socket', 'host': 'printer.lan', 'port': 9100},
        )

    def test_enqueue_persists_only_canonical_target_and_caps_timeout(self):
        result = LocalAgentCommandService().enqueue(
            restaurant=self.restaurant,
            command_type='printer.check',
            payload={'integrationId': str(self.printer.id)},
            timeout_seconds=999,
        )

        command = LocalAgentCommand.objects.get(id=result['commandId'])
        self.assertEqual(command.timeout_seconds, 15)
        self.assertEqual(command.payload['host'], 'printer.lan')
        self.assertEqual(command.payload['port'], 9100)
        self.assertEqual(command.payload['integrationId'], str(self.printer.id))

    def test_denial_records_only_redacted_policy_metadata(self):
        with self.assertRaises(LocalAgentCommandError) as raised:
            LocalAgentCommandService().enqueue(
                restaurant=self.restaurant,
                command_type='printer.check',
                payload={
                    'integrationId': str(self.printer.id),
                    'host': '169.254.169.254',
                    'port': 9100,
                },
            )

        self.assertEqual(raised.exception.code, 'PRINTER_POLICY_DENIED')
        event = SecurityEvent.objects.get(event_type='LOCAL_AGENT_TARGET_DENIED')
        self.assertEqual(
            event.metadata,
            {
                'purpose': 'printer',
                'integrationId': str(self.printer.id),
                'reason': 'not_allowlisted',
            },
        )
        self.assertNotIn('169.254.169.254', str(event.metadata))


class PrinterCheckViewPolicyTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Printer View Restaurant')
        self.printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={'connection_type': 'socket', 'host': 'printer.lan', 'port': 9100},
        )
        self.admin = User.objects.create_superuser(
            username='printer-policy-admin',
            password='Strong-Printer-Policy-123!',
            full_name='Printer Policy Admin',
        )
        request = APIRequestFactory().post(
            '/',
            HTTP_ORIGIN='https://admin.cafe-postcode.uz',
            REMOTE_ADDR='192.0.2.44',
        )
        bundle = AdminAuthService().issue_credentials(
            user=self.admin,
            request=request,
            mfa_verified_at=timezone.now(),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {bundle.access_token}')

    def test_admin_view_cannot_forward_an_arbitrary_host(self):
        response = self.client.post(
            '/api/v1/local-agent/printer/check/',
            {
                'integrationId': str(self.printer.id),
                'connectionType': 'socket',
                'host': '169.254.169.254',
                'port': 9100,
            },
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

        self.assertEqual(response.status_code, 502, response.data)
        self.assertEqual(response.data['code'], 'PRINTER_POLICY_DENIED')
        event = SecurityEvent.objects.get(event_type='LOCAL_AGENT_TARGET_DENIED')
        self.assertEqual(event.metadata['purpose'], 'printer')
        self.assertNotIn('169.254.169.254', str(event.metadata))
