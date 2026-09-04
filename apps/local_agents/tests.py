import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from django.test import TransactionTestCase, override_settings
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.local_agents.models import (
    LocalAgent,
    LocalAgentCommand,
    LocalAgentMutationReceipt,
)
from apps.local_agents.connection_authority import ConnectionIdentity, claim_connection_authority
from apps.local_agents.mutations import _allowed_mutation, _request_hash
from apps.billing.models import CashShift, FiscalShiftSession, Payment, PaymentRefund, Receipt
from apps.local_agents.mutation_reconciliation import reconciled_terminal_noop
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.devices.models import Device
from apps.floor.models import DiningTable, TableSession
from apps.integrations.models import IntegrationConfig
from apps.kitchen.models import KitchenTicket
from apps.printing.models import PrintDocument, PrintTemplate
from apps.printing.services import ensure_restaurant_templates
from apps.restaurants.models import CashDesk, PrepStation, Restaurant
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import Permission, User
from apps.users.models import AuthSession
from apps.users.services import AuthSessionService


class LocalAgentAuthTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant')

    def test_token_auth_returns_agent_metadata(self):
        _agent, token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')

        response = self.client.get('/api/v1/local-agent/auth/token/', HTTP_AUTHORIZATION=f'Bearer {token}')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['agent']['restaurant_name'], 'Agent Restaurant')

    def test_token_auth_rejects_invalid_token(self):
        response = self.client.get('/api/v1/local-agent/auth/token/', HTTP_AUTHORIZATION='Bearer cpa_bad')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_auth_rejects_an_agent_created_after_the_cutover(self):
        now = timezone.now()
        _agent, token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Post-cutover Agent')

        with override_settings(
            DJANGO_PRODUCTION=True,
            DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=True,
            DEVICE_LEGACY_MIGRATION_STARTED_AT=(now - timedelta(hours=1)).isoformat(),
            DEVICE_LEGACY_MIGRATION_DEADLINE=(now + timedelta(hours=1)).isoformat(),
        ):
            response = self.client.get(
                '/api/v1/local-agent/auth/token/',
                HTTP_AUTHORIZATION=f'Bearer {token}',
            )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retired_enrollment_endpoints_do_not_exist(self):
        for path in (
            '/api/v1/local-agent/auth/enroll/',
            '/api/v1/local-agent/auth/enrollment/preflight/',
            '/api/v1/local-agent/auth/restaurant-code/',
            '/api/v1/local-agent/enrollment-token/',
        ):
            with self.subTest(path=path):
                response = self.client.post(path, {'restaurantCode': 'LEGACY'}, format='json')
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocalAgentBrowserSessionSurfaceTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='surface-admin',
            password='Strong-Surface-Password-123!',
        )

    def test_pos_and_dashboard_tokens_cannot_call_admin_local_agent_endpoints(self):
        for surface in (AuthSession.Surface.POS, AuthSession.Surface.DASHBOARD):
            with self.subTest(surface=surface):
                token, _session = AuthSessionService().issue(
                    user=self.user,
                    request=APIRequestFactory().post('/', REMOTE_ADDR='192.0.2.10'),
                    surface=surface,
                )
                self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
                response = self.client.get('/api/v1/local-agent/status/')
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.client.credentials()


class LocalAgentWebSocketSecurityTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='WebSocket Restaurant')
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)

    def test_websocket_requires_bearer_header_and_allowed_origin(self):
        from core.asgi import application

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello['type'], 'hello')
            await communicator.disconnect()

            query_communicator = WebsocketCommunicator(
                application,
                f'/ws/local-agent/?token={self.token}',
                headers=[(b'origin', b'http://testserver')],
            )
            query_connected, _subprotocol = await query_communicator.connect()
            self.assertFalse(query_connected)

        async_to_sync(run_scenario)()

    def test_authoritative_disconnect_marks_agent_offline(self):
        from core.asgi import application

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.status, LocalAgent.Status.OFFLINE)
        self.assertFalse(agent.is_online())

    def test_operational_invalidation_is_delivered_to_connected_agent(self):
        from channels.layers import get_channel_layer

        from apps.local_agents.services import local_agent_group_name
        from core.asgi import application

        agent = LocalAgent.objects.get(restaurant=self.restaurant)

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await get_channel_layer().group_send(
                local_agent_group_name(agent.id),
                {
                    'type': 'operational.invalidate',
                    'server_time': '2026-09-03T12:00:00+05:00',
                },
            )
            message = await communicator.receive_json_from()
            self.assertEqual(message['type'], 'context_invalidated')
            self.assertEqual(message['scopes'], ['operational'])
            self.assertEqual(message['serverTime'], '2026-09-03T12:00:00+05:00')
            await communicator.disconnect()

        async_to_sync(run_scenario)()

    def test_reconnect_receives_device_authority_and_replays_durable_revoke(self):
        from core.asgi import application

        now = timezone.now()
        pos = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Revoked POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='test-public-key',
            public_key_fingerprint='a' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(hours=1),
            status=Device.Status.REVOKED,
            revoked_at=now,
        )
        command = LocalAgentCommand.objects.create(
            agent=LocalAgent.objects.get(restaurant=self.restaurant),
            command_type='edge.terminal.revoke',
            payload={'backendDeviceId': str(pos.id)},
        )

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(
                hello['posDevices'],
                [
                    {
                        'backendDeviceId': str(pos.id),
                        'status': Device.Status.REVOKED,
                        'revokedAt': pos.revoked_at.isoformat(),
                    }
                ],
            )
            delivered = await communicator.receive_json_from()
            self.assertEqual(delivered['type'], 'command')
            self.assertEqual(delivered['commandId'], str(command.id))
            self.assertEqual(delivered['commandType'], 'edge.terminal.revoke')
            self.assertEqual(delivered['payload']['backendDeviceId'], str(pos.id))
            await communicator.send_json_to(
                {'type': 'command_result', 'commandId': str(command.id), 'ok': True, 'result': {'revoked': True}}
            )
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        command.refresh_from_db()
        self.assertEqual(command.status, LocalAgentCommand.Status.SUCCEEDED)

    def test_reconnect_replays_latest_unfinished_update_before_hello(self):
        from core.asgi import application

        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        older = LocalAgentCommand.objects.create(
            agent=agent,
            command_type='agent.update_now',
            status=LocalAgentCommand.Status.TIMED_OUT,
        )
        latest = LocalAgentCommand.objects.create(
            agent=agent,
            command_type='agent.update_now',
            status=LocalAgentCommand.Status.SENT,
        )

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            recovery = await communicator.receive_json_from()
            self.assertEqual(recovery['type'], 'command')
            self.assertEqual(recovery['commandId'], str(latest.id))
            self.assertEqual(recovery['commandType'], 'agent.update_now')
            hello = await communicator.receive_json_from()
            self.assertEqual(hello['type'], 'hello')
            await communicator.send_json_to(
                {
                    'type': 'command_result',
                    'commandId': str(latest.id),
                    'ok': True,
                    'result': {'accepted': True},
                }
            )
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        older.refresh_from_db()
        latest.refresh_from_db()
        self.assertEqual(older.status, LocalAgentCommand.Status.TIMED_OUT)
        self.assertEqual(latest.status, LocalAgentCommand.Status.SUCCEEDED)

    def test_reconnect_does_not_replay_finished_or_unsafe_command_before_hello(self):
        from core.asgi import application

        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        LocalAgentCommand.objects.create(
            agent=agent,
            command_type='agent.update_now',
            status=LocalAgentCommand.Status.SUCCEEDED,
        )
        LocalAgentCommand.objects.create(
            agent=agent,
            command_type='agent.restart',
            status=LocalAgentCommand.Status.TIMED_OUT,
        )

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello['type'], 'hello')
            await communicator.disconnect()

        async_to_sync(run_scenario)()

    def test_heartbeat_persists_private_lan_discovery_metadata(self):
        from core.asgi import application

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.send_json_to(
                {
                    'type': 'heartbeat',
                    'version': '0.6.0',
                    'protocolVersion': 2,
                    'capabilities': ['local_http', 'edge_terminal_issue'],
                    'lanEndpoints': ['http://192.168.1.20:18181', 'https://public.example', 123],
                }
            )
            acknowledgement = await communicator.receive_json_from()
            self.assertEqual(acknowledgement['type'], 'heartbeat_ack')
            self.assertEqual(acknowledgement['posDevices'], [])
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.version, '0.6.0')
        self.assertEqual(agent.protocol_version, 2)
        self.assertEqual(agent.lan_endpoints, ['http://192.168.1.20:18181'])

    def test_paired_agent_heartbeat_updates_device_runtime_version_and_last_seen(self):
        from apps.local_agents.consumers import LocalAgentConsumer

        now = timezone.now()
        device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.LOCAL_AGENT,
            name='Paired Local Agent',
            platform='windows-amd64',
            app_version='1.0.5',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key='test-public-key',
            public_key_fingerprint='b' * 64,
            paired_at=now - timedelta(days=1),
            lease_expires_at=now + timedelta(days=1),
            last_seen_at=now - timedelta(hours=1),
        )
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        agent.device = device
        agent.save(update_fields=['device', 'updated_at'])
        consumer = LocalAgentConsumer()
        consumer.agent = agent
        consumer.device = device
        consumer.connection_id = uuid.uuid4()
        consumer.connection_identity = ConnectionIdentity(
            version='1.1.1',
            runtime_instance_id='abcdefghijklmnopqrstuv',
            protocol_version=3,
            attested=True,
        )
        consumer.channel_name = 'specific.test!connection'
        claim_connection_authority(
            agent_id=agent.pk,
            connection_id=consumer.connection_id,
            channel_name=consumer.channel_name,
            identity=consumer.connection_identity,
        )

        before = timezone.now()
        async_to_sync(consumer._mark_online)(version='1.1.1')

        agent.refresh_from_db()
        device.refresh_from_db()
        self.assertEqual(agent.version, '1.1.1')
        self.assertEqual(device.app_version, '1.1.1')
        self.assertGreaterEqual(device.last_seen_at, before)

    def test_query_token_is_rejected(self):
        from core.asgi import application

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                f'/ws/local-agent/?token={self.token}',
                headers=[(b'origin', b'http://testserver')],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(run_scenario)()

    def test_legacy_websocket_rejects_an_agent_created_after_the_cutover(self):
        from core.asgi import application

        now = timezone.now()

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode('utf-8')),
                ],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertFalse(connected)

        with override_settings(
            DJANGO_PRODUCTION=True,
            DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=True,
            DEVICE_LEGACY_MIGRATION_STARTED_AT=(now - timedelta(hours=1)).isoformat(),
            DEVICE_LEGACY_MIGRATION_DEADLINE=(now + timedelta(hours=1)).isoformat(),
        ):
            async_to_sync(run_scenario)()


class LocalAgentPrintDocumentTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant')
        self.foreign_restaurant = Restaurant.objects.create(name='Foreign Restaurant')
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')
        ensure_restaurant_templates(restaurant=self.restaurant)
        template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        self.printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'socket',
                'host': '192.168.1.50',
                'port': 9100,
                'encoding': 'cp866',
                'code_page': 18,
            },
        )
        self.cash_desk = CashDesk.objects.create(
            restaurant=self.restaurant,
            name='Main cashier',
            printer_integration=self.printer,
        )
        self.document = PrintDocument.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
            idempotency_key='test-document',
            data_snapshot={'restaurant': {'name': 'Agent Restaurant'}},
            template_version=template.published_version,
            content_hash='a' * 64,
            metadata={'cashDeskId': str(self.cash_desk.id)},
        )

    def test_agent_fetches_scoped_document_with_template_and_normalized_route(self):
        response = self.client.get(
            f'/api/v1/local-agent/print-documents/{self.document.id}/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.document.id))
        self.assertEqual(response.data['templateVersion']['revision'], 1)
        self.assertEqual(response.data['route']['printer']['connectionType'], 'socket')
        self.assertEqual(response.data['route']['printer']['codePage'], 18)
        self.assertEqual(response.data['route']['printer']['paperWidthMm'], 80)
        self.assertEqual(response.data['route']['printer']['printMode'], 'text')
        self.assertEqual(response.data['route']['printer']['qrMode'], 'native')
        self.assertEqual(response.data['route']['printer']['rasterFont'], 'go_mono')
        self.assertNotIn('settings', response.data['route']['printer'])

    def test_agent_receives_explicit_raster_output_modes(self):
        self.printer.settings = {
            **self.printer.settings,
            'paper_width_mm': 80,
            'print_mode': 'raster',
            'qr_mode': 'raster',
            'raster_font': 'inter',
        }
        self.printer.save(update_fields=['settings'])

        response = self.client.get(
            f'/api/v1/local-agent/print-documents/{self.document.id}/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        printer = response.data['route']['printer']
        self.assertEqual(printer['paperWidthMm'], 80)
        self.assertEqual(printer['printMode'], 'raster')
        self.assertEqual(printer['qrMode'], 'raster')
        self.assertEqual(printer['rasterFont'], 'inter')

    def test_agent_cannot_fetch_another_restaurants_document(self):
        ensure_restaurant_templates(restaurant=self.foreign_restaurant)
        template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.foreign_restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        document = PrintDocument.objects.create(
            restaurant=self.foreign_restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
            idempotency_key='foreign-document',
            data_snapshot={},
            template_version=template.published_version,
            content_hash='b' * 64,
        )

        response = self.client.get(
            f'/api/v1/local-agent/print-documents/{document.id}/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_agent_resolves_kitchen_document_to_prep_station_printer(self):
        prep_station = PrepStation.objects.create(
            restaurant=self.restaurant,
            name='Hot kitchen',
            printer_integration=self.printer,
        )
        template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.KITCHEN_TICKET,
        )
        document = PrintDocument.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.KITCHEN_TICKET,
            idempotency_key='kitchen-document',
            data_snapshot={'kitchen': {'prepStation': 'Hot kitchen'}},
            template_version=template.published_version,
            content_hash='c' * 64,
            metadata={'prepStationId': str(prep_station.id)},
        )

        response = self.client.get(
            f'/api/v1/local-agent/print-documents/{document.id}/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['route']['prepStationId'], str(prep_station.id))
        self.assertEqual(response.data['route']['printerIntegrationId'], str(self.printer.id))
        self.assertEqual(response.data['route']['printer']['host'], '192.168.1.50')

    def test_document_endpoint_requires_agent_token(self):
        response = self.client.get(f'/api/v1/local-agent/print-documents/{self.document.id}/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class POSRemotePrintTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        ensure_restaurant_templates(restaurant=self.restaurant)
        template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        self.document = PrintDocument.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
            idempotency_key='remote-print-document',
            data_snapshot={},
            template_version=template.published_version,
            content_hash='d' * 64,
        )
        kitchen_template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.KITCHEN_TICKET,
        )
        self.kitchen_document = PrintDocument.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.KITCHEN_TICKET,
            idempotency_key='remote-kitchen-document',
            data_snapshot={},
            template_version=kitchen_template.published_version,
            content_hash='e' * 64,
        )
        precheck_template = PrintTemplate.objects.select_related('published_version').get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        self.precheck_document = PrintDocument.objects.create(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.ORDER_PRECHECK,
            idempotency_key='remote-precheck-document',
            data_snapshot={},
            template_version=precheck_template.published_version,
            content_hash='f' * 64,
        )

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_remote_pos_print_queues_document_for_restaurants_agent(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-123', 'commandStatus': 'pending'}

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:remote-print-123',
                'document_id': str(self.document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        self.assertEqual(response.data['job']['status'], 'queued')
        self.assertEqual(response.data['job']['commandId'], 'command-123')
        enqueue.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='print.document',
            payload={
                'operationId': 'pos:remote-print-123',
                'documentId': str(self.document.id),
                'copies': 1,
            },
            timeout_seconds=100,
        )

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_waiter_can_queue_kitchen_document(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-kitchen', 'commandStatus': 'pending'}
        self.role.permissions.set(Permission.objects.filter(code='pos_tables.manage'))

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:waiter-kitchen-123',
                'document_id': str(self.kitchen_document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        enqueue.assert_called_once()

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_waiter_can_queue_precheck_without_payment_permission(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-precheck', 'commandStatus': 'pending'}
        self.role.permissions.set(Permission.objects.filter(code='pos_tables.manage'))

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:waiter-precheck-123',
                'document_id': str(self.precheck_document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        enqueue.assert_called_once()

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_cashier_can_queue_precheck_with_payment_permission(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-precheck', 'commandStatus': 'pending'}
        self.role.permissions.set(Permission.objects.filter(code='pos_payments.create'))

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:cashier-precheck-123',
                'document_id': str(self.precheck_document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        enqueue.assert_called_once()

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_payment_operator_can_still_queue_kitchen_document(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-kitchen', 'commandStatus': 'pending'}
        self.role.permissions.set(Permission.objects.filter(code='pos_payments.create'))

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:payment-kitchen-123',
                'document_id': str(self.kitchen_document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)
        enqueue.assert_called_once()

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.enqueue')
    def test_waiter_cannot_queue_payment_document(self, enqueue):
        self.role.permissions.set(Permission.objects.filter(code='pos_tables.manage'))

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:waiter-payment-123',
                'document_id': str(self.document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        enqueue.assert_not_called()


class POSSystemStatusTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.agent, _token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name='Site coordinator',
            version='0.8.5',
        )
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

    @patch('apps.local_agents.pos_views.LocalAgentCommandService.enqueue')
    def test_status_returns_recent_cached_result_without_waiting_for_agent(self, enqueue):
        LocalAgentCommand.objects.create(
            agent=self.agent,
            command_type='system.status',
            status=LocalAgentCommand.Status.SUCCEEDED,
            result={
                'agent': {'online': True, 'version': 'old'},
                'backend': {'online': True, 'offlineMode': False},
                'sync': {'ready': True, 'pendingOutbox': 0, 'failedOutbox': 0, 'schemaVersion': 1},
                'fiscal': {'configured': False, 'online': False, 'state': 'not_configured'},
                'marta': {'configured': False, 'online': False, 'state': 'not_configured'},
                'printer': {'configured': True, 'online': True, 'state': 'online'},
                'alerts': [],
            },
            completed_at=timezone.now(),
        )

        response = self.client.get('/api/v1/system/status/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['status']['printer']['online'])
        self.assertEqual(response.data['status']['agent']['version'], '0.8.5')
        enqueue.assert_not_called()

    @patch('apps.local_agents.pos_views.LocalAgentCommandService.enqueue')
    def test_status_schedules_refresh_and_returns_immediately_when_cache_is_empty(self, enqueue):
        enqueue.return_value = {'accepted': True, 'commandId': 'command-123', 'commandStatus': 'pending'}

        response = self.client.get('/api/v1/system/status/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['status']['agent']['online'])
        self.assertEqual(response.data['status']['printer']['state'], 'unknown')
        enqueue.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='system.status',
            payload={},
            timeout_seconds=8,
        )


class LocalAgentBootstrapTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.user.set_pin('1234')
        self.user.save(update_fields=['pin_code'])
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')

    def test_bootstrap_returns_offline_context_scoped_to_agent_restaurant(self):
        self.restaurant.payment_total_mode = Restaurant.PaymentTotalMode.CASHIER_EDITABLE
        self.restaurant.save(update_fields=['payment_total_mode', 'updated_at'])
        shift = CashShift.objects.create(
            cash_desk=self.cash_desk,
            cashier=self.user,
            opened_by=self.user,
            status=CashShift.Status.OPEN,
            opened_at=timezone.now(),
            opening_cash_amount=125000,
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=77,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=40000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )
        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['schemaVersion'], 1)
        self.assertEqual(response.data['restaurant']['restaurant_id'], str(self.restaurant.id))
        self.assertEqual(response.data['restaurant']['payment_total_mode'], 'cashier_editable')
        self.assertEqual(response.data['users'][0]['userId'], str(self.user.id))
        self.assertTrue(response.data['users'][0]['pinHash'].startswith('pbkdf2_'))
        self.assertGreaterEqual(len(response.data['menu']), 1)
        self.assertGreaterEqual(len(response.data['halls']), 1)
        self.assertEqual(response.data['bindings']['cashDesks'][0]['id'], str(self.cash_desk.id))
        self.assertEqual(response.data['cashShifts'][0]['id'], str(shift.id))
        self.assertEqual(response.data['cashShifts'][0]['cashier'], str(self.user.id))
        self.assertEqual(response.data['cashShifts'][0]['openingCashAmount'], 125000)
        self.assertEqual(response.data['cashShifts'][0]['cashPrecheckTotal'], 40000)
        self.assertEqual(response.data['cashShifts'][0]['cashReceiptTotal'], 0)
        self.assertEqual(response.data['cashShifts'][0]['cardPrecheckTotal'], 0)
        self.assertEqual(response.data['cashShifts'][0]['cardReceiptTotal'], 0)
        self.assertEqual(response.data['cashShifts'][0]['saleCount'], 1)
        self.assertEqual(response.data['cashShifts'][0]['totalSaleAmount'], 40000)
        self.assertEqual(response.data['posDevices'], [])

    def test_split_snapshots_partition_configuration_from_live_state_without_data_gaps(self):
        shift = self.create_cash_shift()
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=78,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
        )

        configuration = self.client.get(
            '/api/v1/local-agent/sync/configuration/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        operational = self.client.get(
            '/api/v1/local-agent/sync/operational/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        legacy = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(configuration.status_code, status.HTTP_200_OK, configuration.data)
        self.assertEqual(operational.status_code, status.HTTP_200_OK, operational.data)
        self.assertEqual(legacy.status_code, status.HTTP_200_OK, legacy.data)
        configuration_fields = {
            'restaurant', 'posDevices', 'users', 'menu', 'expenseCategories',
            'expenseRecipients', 'bindings', 'printTemplates',
        }
        operational_fields = {
            'halls', 'tableSessions', 'orders', 'kitchenTickets', 'cashShifts', 'cashExpenses',
        }
        self.assertTrue(configuration_fields.issubset(configuration.data))
        self.assertTrue(operational_fields.issubset(operational.data))
        self.assertTrue(configuration_fields.isdisjoint(operational.data))
        self.assertTrue(operational_fields.isdisjoint(configuration.data))
        for field in configuration_fields:
            if field == 'users':
                configuration_users = {
                    item['userId']: (item['pinHash'], item['session'])
                    for item in configuration.data[field]
                }
                legacy_users = {
                    item['userId']: (item['pinHash'], item['session'])
                    for item in legacy.data[field]
                }
                self.assertEqual(configuration_users, legacy_users, field)
            else:
                self.assertEqual(configuration.data[field], legacy.data[field], field)
        for field in operational_fields:
            self.assertEqual(operational.data[field], legacy.data[field], field)
        self.assertIn(str(order.id), [str(item['id']) for item in operational.data['orders']])
        self.assertIn(str(shift.id), [str(item['id']) for item in operational.data['cashShifts']])

    def test_split_snapshots_require_header_agent_authentication(self):
        for path in (
            '/api/v1/local-agent/sync/configuration/',
            '/api/v1/local-agent/sync/operational/',
        ):
            with self.subTest(path=path):
                missing = self.client.get(path)
                query = self.client.get(f'{path}?token={self.token}')
                self.assertEqual(missing.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(query.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bootstrap_carries_printer_output_modes_for_offline_printing(self):
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.PRINTER,
            provider='windows-raw',
            settings={
                'connection_type': 'system_printer',
                'printer_name': 'XP-H200N',
                'paper_width_mm': 80,
                'print_mode': 'raster',
                'qr_mode': 'raster',
            },
        )
        self.cash_desk.printer_integration = printer
        self.cash_desk.save(update_fields=['printer_integration'])

        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        integration = next(
            item for item in response.data['bindings']['integrations']
            if item['id'] == str(printer.id)
        )
        self.assertEqual(integration['settings']['print_mode'], 'raster')
        self.assertEqual(integration['settings']['qr_mode'], 'raster')
        self.assertEqual(
            response.data['bindings']['cashDesks'][0]['printerIntegrationId'],
            str(printer.id),
        )

    def test_device_state_endpoint_is_complete_and_restaurant_scoped(self):
        now = timezone.now()
        active = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Active POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='active-public-key',
            public_key_fingerprint='b' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(hours=1),
        )
        revoked = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Revoked POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='revoked-public-key',
            public_key_fingerprint='c' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(hours=1),
            status=Device.Status.REVOKED,
            revoked_at=now,
        )
        foreign_restaurant = Restaurant.objects.create(name='Foreign device authority tenant')
        Device.objects.create(
            restaurant=foreign_restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Foreign POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='foreign-public-key',
            public_key_fingerprint='d' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(hours=1),
        )

        response = self.client.get(
            '/api/v1/local-agent/sync/pos-device-state/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {item['backendDeviceId']: item for item in response.data['posDevices']}
        self.assertEqual(set(by_id), {str(active.id), str(revoked.id)})
        self.assertEqual(by_id[str(active.id)]['status'], Device.Status.ACTIVE)
        self.assertIsNone(by_id[str(active.id)]['revokedAt'])
        self.assertEqual(by_id[str(revoked.id)]['status'], Device.Status.REVOKED)
        self.assertIsNotNone(by_id[str(revoked.id)]['revokedAt'])

    def test_bootstrap_requires_agent_token(self):
        response = self.client.get('/api/v1/local-agent/sync/bootstrap/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bootstrap_rejects_agent_token_in_query_string(self):
        response = self.client.get(f'/api/v1/local-agent/sync/bootstrap/?token={self.token}')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bootstrap_includes_hall_table_and_effective_session_service_fees(self):
        self.hall.service_fee_enabled = True
        self.hall.service_fee_percent = 3
        self.hall.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        self.table.service_fee_enabled = True
        self.table.service_fee_percent = 2
        self.table.save(update_fields=['service_fee_enabled', 'service_fee_percent'])
        table_session = self.create_table_session()

        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        hall = next(row for row in response.data['halls'] if str(row['id']) == str(self.hall.id))
        table = next(row for row in hall['tables'] if str(row['id']) == str(self.table.id))
        session = next(
            row for row in response.data['tableSessions'] if str(row['id']) == str(table_session.id)
        )
        self.assertTrue(hall['service_fee_enabled'])
        self.assertEqual(hall['service_fee_percent'], 3)
        self.assertTrue(table['service_fee_enabled'])
        self.assertEqual(table['service_fee_percent'], 2)
        self.assertEqual(session['service_fee_percent'], 15)
        self.assertEqual(
            [component['scope'] for component in session['service_fee_components']],
            ['restaurant', 'hall', 'table'],
        )

    def test_bootstrap_keeps_grouped_secondary_table_on_the_same_session(self):
        source = self.create_table_session(table=self.table, guest_count=2)
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        secondary = DiningTable.objects.create(
            hall=self.hall,
            zone=self.zone,
            name='Grouped secondary',
            table_number=2,
            seat_count=4,
        )
        grouped = self.client.post(
            f'/api/v1/pos/floor/table-sessions/{source.pk}/group/',
            {'tableIds': [str(secondary.pk)]},
            format='json',
        )
        self.assertEqual(grouped.status_code, status.HTTP_200_OK, grouped.data)

        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        hall = next(row for row in response.data['halls'] if str(row['id']) == str(self.hall.pk))
        by_id = {str(row['id']): row for row in hall['tables']}
        for table_id in (str(self.table.pk), str(secondary.pk)):
            self.assertEqual(str(by_id[table_id]['active_session']['id']), str(source.pk))
            self.assertCountEqual(
                [str(value) for value in by_id[table_id]['active_session']['table_ids']],
                [str(self.table.pk), str(secondary.pk)],
            )

    def test_bootstrap_excludes_stale_kitchen_ticket_for_closed_order(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=9091,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            closed_at=timezone.now() - timedelta(days=2),
        )
        ticket = KitchenTicket.objects.create(
            restaurant=self.restaurant,
            order=order,
            prep_station=self.prep_station,
            status=KitchenTicket.Status.NEW,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        KitchenTicket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(days=2))

        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(ticket.id), [str(item['id']) for item in response.data['kitchenTickets']])

    def test_bootstrap_kitchen_ticket_selection_matrix(self):
        now = timezone.now()

        def create_ticket(
            *,
            number,
            order_status,
            ticket_status,
            age,
            completed_age=None,
            channel=Order.Channel.TAKEAWAY,
        ):
            order = Order.objects.create(
                restaurant=self.restaurant,
                distribution_point=(
                    self.hall_distribution if channel == Order.Channel.HALL else self.takeaway_distribution
                ),
                opened_by=self.user,
                order_number=number,
                channel=channel,
                status=order_status,
                closed_at=now if order_status == Order.Status.CLOSED else None,
            )
            ticket = KitchenTicket.objects.create(
                restaurant=self.restaurant,
                order=order,
                prep_station=self.prep_station,
                status=ticket_status,
                routed_via=KitchenTicket.RouteMode.BOTH,
                completed_at=now - completed_age if completed_age is not None else None,
            )
            KitchenTicket.objects.filter(pk=ticket.pk).update(created_at=now - age)
            return ticket

        active_old = create_ticket(
            number=9101,
            order_status=Order.Status.OPEN,
            ticket_status=KitchenTicket.Status.NEW,
            age=timedelta(days=2),
        )
        closed_fresh = create_ticket(
            number=9102,
            order_status=Order.Status.CLOSED,
            ticket_status=KitchenTicket.Status.COOKING,
            age=timedelta(hours=23),
        )
        closed_stale = create_ticket(
            number=9103,
            order_status=Order.Status.CLOSED,
            ticket_status=KitchenTicket.Status.NEW,
            age=timedelta(hours=25),
        )
        recently_done_closed = create_ticket(
            number=9104,
            order_status=Order.Status.CLOSED,
            ticket_status=KitchenTicket.Status.DONE,
            age=timedelta(minutes=1),
            completed_age=timedelta(minutes=1),
            channel=Order.Channel.HALL,
        )
        done_within_pos_history = create_ticket(
            number=9105,
            order_status=Order.Status.OPEN,
            ticket_status=KitchenTicket.Status.DONE,
            age=timedelta(minutes=3),
            completed_age=timedelta(minutes=3),
        )
        done_outside_pos_history = create_ticket(
            number=9106,
            order_status=Order.Status.OPEN,
            ticket_status=KitchenTicket.Status.DONE,
            age=timedelta(hours=25),
            completed_age=timedelta(hours=25),
        )

        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        ticket_ids = [str(item['id']) for item in response.data['kitchenTickets']]
        self.assertIn(str(active_old.id), ticket_ids)
        self.assertIn(str(closed_fresh.id), ticket_ids)
        self.assertNotIn(str(closed_stale.id), ticket_ids)
        self.assertIn(str(recently_done_closed.id), ticket_ids)
        self.assertIn(str(done_within_pos_history.id), ticket_ids)
        self.assertNotIn(str(done_outside_pos_history.id), ticket_ids)
        self.assertLess(ticket_ids.index(str(active_old.id)), ticket_ids.index(str(closed_fresh.id)))


class LocalAgentOperationalInvalidationTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        _agent, self.token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name='Site coordinator',
        )

    @patch('core.middleware.local_agent_invalidation.broadcast_operational_invalidation')
    def test_successful_direct_pos_mutation_wakes_restaurant_agent_after_commit(self, broadcast):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/v1/pos/sales/orders/',
                {'channel': 'takeaway', 'guestCount': 1},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        broadcast.assert_called_once_with(restaurant_id=self.restaurant.id)

    @patch('core.middleware.local_agent_invalidation.broadcast_operational_invalidation')
    def test_rejected_direct_pos_mutation_does_not_emit_false_invalidation(self, broadcast):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/v1/pos/sales/orders/',
                {'channel': 'not-a-channel', 'guestCount': 1},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        broadcast.assert_not_called()

    @patch('core.middleware.local_agent_invalidation.broadcast_operational_invalidation')
    def test_agent_outbox_replay_does_not_echo_an_invalidation_back_to_itself(self, broadcast):
        operation = {
            'operationId': 'edge-no-invalidation-echo',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/sales/orders/',
            'body': {
                'id': str(uuid.uuid4()),
                'channel': 'takeaway',
                'guestCount': 1,
            },
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/v1/local-agent/sync/mutations/',
                {'operations': [operation]},
                format='json',
                HTTP_AUTHORIZATION=f'Bearer {self.token}',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['results'][0]['ok'], response.data)
        broadcast.assert_not_called()

    @patch('apps.local_agents.invalidation.get_channel_layer', return_value=None)
    def test_invalidation_transport_failure_never_rolls_back_a_pos_mutation(self, _channel_layer):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                '/api/v1/pos/sales/orders/',
                {'channel': 'takeaway', 'guestCount': 1},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Order.objects.filter(pk=response.data['id']).exists())


class LocalAgentMutationPushTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')

    def test_order_create_mutation_is_replayed_once(self):
        order_id = uuid.uuid4()
        occurred_at = (timezone.now() - timedelta(hours=8)).replace(microsecond=123456)
        operation = {
            'operationId': 'edge-order-create-1',
            'userId': str(self.user.id),
            'occurredAt': occurred_at.isoformat(),
            'method': 'POST',
            'path': '/api/v1/pos/sales/orders/',
            'body': {
                'id': str(order_id),
                'channel': 'takeaway',
                'guestCount': 1,
                'note': 'offline order',
            },
        }
        first = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        second = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(first.data['results'][0]['status'], status.HTTP_201_CREATED, first.data)
        self.assertFalse(first.data['results'][0]['replayed'])
        self.assertTrue(second.data['results'][0]['replayed'])
        self.assertEqual(Order.objects.filter(id=order_id, restaurant=self.restaurant).count(), 1)
        order = Order.objects.get(id=order_id, restaurant=self.restaurant)
        self.assertEqual(order.created_at, occurred_at)

    def test_future_order_occurrence_time_is_quarantined(self):
        order_id = uuid.uuid4()
        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [
                    {
                        'operationId': 'edge-order-future-time',
                        'userId': str(self.user.id),
                        'occurredAt': (timezone.now() + timedelta(hours=1)).isoformat(),
                        'method': 'POST',
                        'path': '/api/v1/pos/sales/orders/',
                        'body': {
                            'id': str(order_id),
                            'channel': 'takeaway',
                            'guestCount': 1,
                        },
                    }
                ]
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        result = response.data['results'][0]
        self.assertEqual(result['status'], status.HTTP_400_BAD_REQUEST)
        self.assertEqual(result['code'], 'INVALID_OPERATION_OCCURRED_AT')
        self.assertEqual(result['classification'], 'quarantined')
        self.assertFalse(Order.objects.filter(id=order_id).exists())

    def test_table_transfer_mutation_is_replayed_once(self):
        source = self.create_table_session(table=self.table, guest_count=2)
        self.table.status = DiningTable.Status.OCCUPIED
        self.table.save(update_fields=['status', 'updated_at'])
        target = DiningTable.objects.create(
            hall=self.hall,
            zone=self.zone,
            name='Replay target',
            table_number=2,
            seat_count=4,
        )
        operation = {
            'operationId': 'edge-table-transfer-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/floor/table-sessions/{source.pk}/transfer/',
            'body': {
                'targetTableId': str(target.pk),
                'expectedTargetSessionIds': [],
            },
        }

        first = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        second = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(first.data['results'][0]['status'], status.HTTP_200_OK, first.data)
        self.assertFalse(first.data['results'][0]['replayed'])
        self.assertTrue(second.data['results'][0]['replayed'])
        source.refresh_from_db()
        self.table.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.status, TableSession.Status.OPEN)
        self.assertEqual(source.table_id, target.pk)
        self.assertEqual(self.table.status, DiningTable.Status.AVAILABLE)
        self.assertEqual(target.status, DiningTable.Status.OCCUPIED)

    def test_revoked_originating_pos_device_is_denied_even_for_inflight_batch(self):
        now = timezone.now()
        device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.POS_TERMINAL,
            name='Revoked mutation origin',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='revoked-mutation-public-key',
            public_key_fingerprint='e' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(hours=1),
            status=Device.Status.REVOKED,
            revoked_at=now,
        )
        order_id = uuid.uuid4()

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [
                    {
                        'operationId': 'edge-revoked-device-inflight',
                        'userId': str(self.user.id),
                        'deviceId': str(device.id),
                        'method': 'POST',
                        'path': '/api/v1/pos/sales/orders/',
                        'body': {'id': str(order_id), 'channel': 'takeaway', 'guestCount': 1},
                    }
                ]
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        result = response.data['results'][0]
        self.assertEqual(result['status'], status.HTTP_403_FORBIDDEN)
        self.assertEqual(result['code'], 'POS_DEVICE_INVALID')
        self.assertFalse(Order.objects.filter(id=order_id).exists())

    def test_trusted_edge_create_preserves_ids_but_cannot_override_initial_status(self):
        order_id = uuid.uuid4()
        item_id = uuid.uuid4()
        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [
                    {
                        'operationId': 'edge-explicit-order-id',
                        'userId': str(self.user.id),
                        'method': 'POST',
                        'path': '/api/v1/pos/sales/orders/',
                        'body': {
                            'id': str(order_id),
                            'channel': Order.Channel.TAKEAWAY,
                            'guestCount': 1,
                        },
                    },
                    {
                        'operationId': 'edge-explicit-item-id',
                        'userId': str(self.user.id),
                        'method': 'POST',
                        'path': f'/api/v1/pos/sales/orders/{order_id}/items/',
                        'body': {
                            'id': str(item_id),
                            'catalogItem': str(self.catalog_item.id),
                            'quantity': 1,
                        },
                    },
                ]
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            [result['status'] for result in response.data['results']],
            [status.HTTP_201_CREATED, status.HTTP_201_CREATED],
            response.data,
        )
        self.assertTrue(Order.objects.filter(pk=order_id, status=Order.Status.OPEN).exists())
        self.assertTrue(OrderItem.objects.filter(pk=item_id, order_id=order_id, status=OrderItem.Status.NEW).exists())

        malicious_order_id = uuid.uuid4()
        malicious_item_id = uuid.uuid4()
        malicious = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [
                    {
                        'operationId': 'edge-malicious-order-status',
                        'userId': str(self.user.id),
                        'method': 'POST',
                        'path': '/api/v1/pos/sales/orders/',
                        'body': {
                            'id': str(malicious_order_id),
                            'channel': Order.Channel.TAKEAWAY,
                            'guestCount': 1,
                            'status': Order.Status.CLOSED,
                        },
                    },
                    {
                        'operationId': 'edge-malicious-item-status',
                        'userId': str(self.user.id),
                        'method': 'POST',
                        'path': f'/api/v1/pos/sales/orders/{order_id}/items/',
                        'body': {
                            'id': str(malicious_item_id),
                            'catalogItem': str(self.catalog_item.id),
                            'quantity': 1,
                            'status': OrderItem.Status.DONE,
                        },
                    },
                ]
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(malicious.status_code, status.HTTP_200_OK, malicious.data)
        self.assertEqual(
            [result['status'] for result in malicious.data['results']],
            [status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST],
            malicious.data,
        )
        self.assertFalse(Order.objects.filter(pk=malicious_order_id).exists())
        self.assertFalse(OrderItem.objects.filter(pk=malicious_item_id).exists())

    def test_offline_order_numbers_advance_canonical_shift_counter(self):
        shift = self.create_cash_shift(cash_desk=self.cash_desk, opened_by=self.user)
        operations = [
            {
                'operationId': f'edge-order-number-{index}',
                'userId': str(self.user.id),
                'method': 'POST',
                'path': '/api/v1/pos/sales/orders/',
                'body': {
                    'id': str(uuid.uuid4()),
                    'channel': 'takeaway',
                    'guestCount': 1,
                    # Reproduce a stale Local Agent counter. The backend must
                    # not persist the same visible number twice.
                    'displayName': '1',
                },
            }
            for index in range(2)
        ]

        first = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': operations},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        replay = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': operations},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual([item['status'] for item in first.data['results']], [201, 201], first.data)
        display_names = list(
            Order.objects.filter(id__in=[item['body']['id'] for item in operations])
            .order_by('created_at')
            .values_list('display_name', flat=True)
        )
        self.assertEqual(display_names, ['1', '2'])
        self.assertTrue(all(item['replayed'] for item in replay.data['results']))
        shift.refresh_from_db()
        self.assertEqual(shift.next_order_number, 2)

        bootstrap = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(bootstrap.status_code, status.HTTP_200_OK, bootstrap.data)
        self.assertEqual(bootstrap.data['cashShifts'][0]['nextOrderNumber'], 2)

        online_order = self.client.post(
            '/api/v1/pos/sales/orders/',
            {
                'distributionPoint': str(self.takeaway_distribution.id),
                'channel': 'takeaway',
                'guestCount': 1,
            },
            format='json',
        )
        self.assertEqual(online_order.status_code, status.HTTP_201_CREATED, online_order.data)
        self.assertEqual(online_order.data['display_name'], '3')

    def test_mutation_rejects_non_pos_path(self):
        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [
                    {
                        'operationId': 'edge-admin-write-1',
                        'userId': str(self.user.id),
                        'method': 'POST',
                        'path': '/api/v1/admin/restaurants/',
                        'body': {},
                    }
                ]
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['results'][0]['status'], status.HTTP_403_FORBIDDEN)

    def test_missing_order_item_delete_is_reconciled_as_success(self):
        operation = {
            'operationId': 'edge-delete-missing-item-1',
            'userId': str(self.user.id),
            'method': 'DELETE',
            'path': f'/api/v1/pos/sales/orders/items/{uuid.uuid4()}/',
            'body': {},
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertTrue(result['reconciled'])
        self.assertEqual(result['status'], status.HTTP_204_NO_CONTENT)
        self.assertEqual(result['body']['reason'], 'already_absent')

    def test_legacy_failed_delete_on_closed_order_is_reconciled_when_replayed(self):
        item_id = uuid.uuid4()
        operation = {
            'operationId': 'edge-delete-closed-item-1',
            'userId': str(self.user.id),
            'method': 'DELETE',
            'path': f'/api/v1/pos/sales/orders/items/{item_id}/',
            'body': {},
        }
        receipt = LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant,
            operation_id=operation['operationId'],
            user_id=self.user.id,
            method=operation['method'],
            path=operation['path'],
            request_hash=_request_hash(
                user_id=str(self.user.id),
                method=operation['method'],
                path=operation['path'],
                body={},
            ),
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={'detail': 'Closed or cancelled orders cannot be modified.'},
        )

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertTrue(result['reconciled'])
        self.assertEqual(result['status'], status.HTTP_204_NO_CONTENT)
        receipt.refresh_from_db()
        self.assertEqual(receipt.response_status, status.HTTP_204_NO_CONTENT)
        self.assertEqual(receipt.response_body['reason'], 'order_already_finalized')

    def test_legacy_payment_conflict_is_reconciled_when_order_is_fully_paid(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=9090,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            subtotal=71000,
            total=71000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=71000,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        operation = {
            'operationId': 'edge-legacy-duplicate-payment-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
            'body': {'method': 'cash', 'amount': 71000},
        }
        receipt = LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant,
            operation_id=operation['operationId'],
            user_id=self.user.id,
            method=operation['method'],
            path=operation['path'],
            request_hash=_request_hash(
                user_id=str(self.user.id),
                method=operation['method'],
                path=operation['path'],
                body=operation['body'],
            ),
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={'amount': 'Payment amount cannot exceed the remaining total.'},
        )

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertTrue(result['reconciled'])
        self.assertEqual(result['status'], status.HTTP_200_OK)
        self.assertEqual(result['body']['reason'], 'order_already_fully_paid')
        receipt.refresh_from_db()
        self.assertEqual(receipt.response_status, status.HTTP_200_OK)

    def test_duplicate_payment_on_closed_fully_paid_order_is_reconciled_immediately(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=9091,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            subtotal=48000,
            total=48000,
            closed_at=timezone.now(),
        )
        Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=48000,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        operation = {
            'operationId': 'edge-duplicate-closed-payment-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
            'body': {'method': 'cash', 'amount': 40000},
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertTrue(result['reconciled'])
        self.assertFalse(result['replayed'])
        self.assertEqual(result['status'], status.HTTP_200_OK)
        self.assertEqual(result['body']['reason'], 'order_already_fully_paid')
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        receipt = LocalAgentMutationReceipt.objects.get(operation_id=operation['operationId'])
        self.assertEqual(receipt.response_status, status.HTTP_200_OK)
        self.assertEqual(receipt.response_body['reason'], 'order_already_fully_paid')

    def test_report_without_active_shift_is_reconciled_immediately(self):
        operation = {
            'operationId': 'edge-report-without-shift-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/shifts/current/print-report/',
            'body': {},
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        result = response.data['results'][0]
        self.assertTrue(result['ok'], response.data)
        self.assertTrue(result['reconciled'])
        self.assertEqual(result['status'], status.HTTP_200_OK)
        self.assertEqual(result['body']['reason'], 'report_shift_already_absent')

    def test_already_refunded_payment_is_a_reconciled_noop(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=9092,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            subtotal=52000,
            total=52000,
            closed_at=timezone.now(),
        )
        payment = Payment.objects.create(
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=52000,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        PaymentRefund.objects.create(
            payment=payment,
            amount=52000,
            refunded_by=self.user,
            status=PaymentRefund.Status.SUCCEEDED,
            refunded_at=timezone.now(),
        )

        result = reconciled_terminal_noop(
            agent=LocalAgent.objects.get(restaurant=self.restaurant),
            method='POST',
            path=f'/api/v1/pos/billing/{payment.id}/refund/',
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={'detail': 'This payment has already been refunded.'},
        )

        self.assertEqual(result['reason'], 'payment_already_fully_refunded')
        self.assertEqual(result['paymentId'], str(payment.id))

    def test_online_only_pos_commands_are_allowed_through_agent_replay(self):
        payment_id = uuid.uuid4()
        paths = (
            f'/api/v1/pos/billing/payments/{payment_id}/retry-fiscal/',
            f'/api/v1/pos/billing/payments/{payment_id}/print-document/',
            f'/api/v1/pos/billing/{payment_id}/refund/',
            '/api/v1/pos/billing/fiscal-shifts/open/',
            '/api/v1/pos/billing/fiscal-shifts/close/',
        )

        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(_allowed_mutation('POST', path))

    def test_offline_shift_close_maps_edge_shift_to_canonical_shift(self):
        edge_shift_id = uuid.uuid4()
        operations = [
            {
                'operationId': 'edge-shift-open-1',
                'userId': str(self.user.id),
                'method': 'POST',
                'path': '/api/v1/pos/billing/shifts/open/',
                'body': {
                    'edgeCashShiftId': str(edge_shift_id),
                    'cashDeskId': str(self.cash_desk.id),
                    'openingCashAmount': 10000,
                },
            },
            {
                'operationId': 'edge-shift-close-1',
                'userId': str(self.user.id),
                'method': 'POST',
                'path': '/api/v1/pos/billing/shifts/current/close/',
                'body': {
                    'edgeCashShiftId': str(edge_shift_id),
                    'edgeCashDeskId': str(self.cash_desk.id),
                    'edgeCashierId': str(self.user.id),
                    'actualClosingCashAmount': 10000,
                    'closeFiscalShift': False,
                },
            },
        ]

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': operations},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([item['status'] for item in response.data['results']], [201, 200], response.data)
        shift = CashShift.objects.get(cash_desk__restaurant=self.restaurant, opened_by=self.user)
        self.assertEqual(shift.id, edge_shift_id)
        self.assertEqual(shift.status, CashShift.Status.CLOSED)

    def test_delayed_edge_payment_never_moves_to_new_shift(self):
        order_data = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order_data['id'])
        old_shift = self.create_cash_shift()
        old_shift.status = CashShift.Status.CLOSED
        old_shift.closed_at = timezone.now()
        old_shift.save(update_fields=['status', 'closed_at', 'updated_at'])
        new_shift = self.create_cash_shift()
        order = Order.objects.get(pk=order_data['id'])

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {
                'operations': [{
                    'operationId': 'edge-payment-old-shift-1',
                    'userId': str(self.user.id),
                    'method': 'POST',
                    'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
                    'body': {
                        'edgeCashShiftId': str(old_shift.id),
                        'method': 'cash',
                        'amount': order.total,
                        'registerFiscal': False,
                    },
                }],
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        result = response.data['results'][0]
        self.assertFalse(result['ok'], response.data)
        self.assertEqual(result['status'], status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Payment.objects.filter(cash_shift=new_shift).exists())

    def test_offline_shift_open_reconciles_same_existing_canonical_shift(self):
        existing_shift = self.create_cash_shift(cash_desk=self.cash_desk, opened_by=self.user)
        operation = {
            'operationId': 'edge-shift-open-existing-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/shifts/open/',
            'body': {
                'cashDeskId': str(self.cash_desk.id),
                'cashierId': str(self.user.id),
                'openingCashAmount': 0,
            },
        }
        LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant,
            operation_id=operation['operationId'],
            user_id=self.user.id,
            method=operation['method'],
            path=operation['path'],
            request_hash=_request_hash(
                user_id=str(self.user.id),
                method=operation['method'],
                path=operation['path'],
                body={
                    'cash_desk_id': str(self.cash_desk.id),
                    'cashier_id': str(self.user.id),
                    'opening_cash_amount': 0,
                },
            ),
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={'cashDeskId': 'Selected cash desk already has an active shift.'},
        )

        first = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        second = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        first_result = first.data['results'][0]
        self.assertEqual(first_result['status'], status.HTTP_200_OK, first.data)
        self.assertTrue(first_result['ok'])
        self.assertTrue(first_result['reconciled'])
        self.assertEqual(first_result['body']['currentShift']['id'], str(existing_shift.id))
        self.assertTrue(second.data['results'][0]['replayed'])
        self.assertEqual(CashShift.objects.filter(cash_desk=self.cash_desk, status=CashShift.Status.OPEN).count(), 1)

    def test_offline_shift_open_recovers_legacy_manager_as_cashier_payload(self):
        operation = {
            'operationId': 'edge-shift-open-implicit-manager-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/shifts/open/',
            'body': {
                'cashDeskId': str(self.cash_desk.id),
                'cashierId': str(self.user.id),
                'openingCashAmount': 0,
            },
        }
        LocalAgentMutationReceipt.objects.create(
            restaurant=self.restaurant,
            operation_id=operation['operationId'],
            user_id=self.user.id,
            method=operation['method'],
            path=operation['path'],
            request_hash=_request_hash(
                user_id=str(self.user.id),
                method=operation['method'],
                path=operation['path'],
                body={
                    'cash_desk_id': str(self.cash_desk.id),
                    'cashier_id': str(self.user.id),
                    'opening_cash_amount': 0,
                },
            ),
            response_status=status.HTTP_400_BAD_REQUEST,
            response_body={'cashierId': 'Selected cashier was not found.'},
        )

        first = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        second = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        first_result = first.data['results'][0]
        self.assertEqual(first_result['status'], status.HTTP_201_CREATED, first.data)
        self.assertTrue(first_result['ok'])
        shift = CashShift.objects.get(cash_desk=self.cash_desk, status=CashShift.Status.OPEN)
        self.assertEqual(shift.opened_by_id, self.user.id)
        self.assertIsNone(shift.cashier_id)
        self.assertTrue(second.data['results'][0]['replayed'])

    @patch('apps.billing.services.order_payment.charge_payment')
    def test_trusted_edge_card_result_is_replayed_without_second_terminal_charge(self, charge_payment):
        order_data = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order_data['id'])
        self.create_cash_shift()
        order = Order.objects.get(id=order_data['id'])
        operation_id = 'edge-card-payment-1'
        operation = {
            'operationId': operation_id,
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
            'body': {
                'method': 'card',
                'amount': order.total,
                'edgeOperationId': operation_id,
                'edgeProviderResult': {
                    'ok': True,
                    'provider': 'marta-softpos',
                    'status': 'SUCCESS',
                    'reference': 'trx-edge-1',
                    'cardAmount': order.total,
                    'edgeOperationId': operation_id,
                },
            },
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['results'][0]['status'], status.HTTP_201_CREATED, response.data)
        charge_payment.assert_not_called()
        payment = Payment.objects.get(order=order)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_ref, 'trx-edge-1')
        self.assertTrue(payment.provider_payload['trustedEdgeReplay'])

    @patch('apps.billing.services.order_payment.issue_fiscal_receipts')
    def test_trusted_edge_fiscal_result_is_persisted_without_remote_fiscal_call(self, issue_fiscal_receipts):
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'endpoint_url': 'http://127.0.0.1:3449'},
        )
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])
        order_data = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order_data['id'])
        self.create_cash_shift()
        order = Order.objects.get(id=order_data['id'])
        operation = {
            'operationId': 'edge-local-fiscal-payment-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
            'body': {
                'method': 'cash',
                'amount': order.total,
                'registerFiscal': True,
                'edgeFiscalResultsJson': json.dumps([{
                    'ok': True,
                    'provider': 'fiscal-drive-service',
                    'receipt_number': '71',
                    'terminal_id': 'TERM-1',
                    'fiscal_sign': '123',
                    'qr_code_url': 'https://ofd.uz/71',
                    'response': {'TerminalID': 'TERM-1', 'ReceiptSeq': 71},
                    'request': {'receipt': {'ReceivedCash': order.total * 100, 'ReceivedCard': 0}},
                }]),
            },
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['results'][0]['status'], status.HTTP_201_CREATED, response.data)
        issue_fiscal_receipts.assert_not_called()
        receipt = Receipt.objects.get(order=order, kind=Receipt.Kind.FISCAL)
        self.assertEqual(receipt.status, Receipt.Status.SENT)
        self.assertEqual(receipt.payload['receipt_number'], '71')
        self.assertEqual(receipt.payload['response']['TerminalID'], 'TERM-1')
        self.assertEqual(receipt.payload['request']['receipt']['ReceivedCash'], order.total * 100)

    def test_browser_cannot_submit_edge_fiscal_result(self):
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'endpoint_url': 'http://127.0.0.1:3449'},
        )
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])
        order_data = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order_data['id'])
        self.create_cash_shift()
        order = Order.objects.get(id=order_data['id'])

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{order.id}/pay/',
            {
                'method': 'cash',
                'amount': order.total,
                'registerFiscal': True,
                'edgeFiscalResultsJson': json.dumps([{'ok': True, 'provider': 'fiscal-drive-service'}]),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(Payment.objects.filter(order=order).exists())

    @patch('apps.billing.services.order_payment.issue_fiscal_receipts')
    def test_trusted_edge_fiscal_retry_uses_local_result_without_remote_fiscal_call(self, issue_fiscal_receipts):
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'endpoint_url': 'http://127.0.0.1:3449'},
        )
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])
        order_data = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order_data['id'])
        self.create_cash_shift()
        order = Order.objects.get(id=order_data['id'])
        payment_operation = {
            'operationId': 'edge-local-fiscal-failed-payment-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/orders/{order.id}/pay/',
            'body': {
                'method': 'cash',
                'amount': order.total,
                'registerFiscal': True,
                'edgeFiscalResultsJson': json.dumps([{
                    'ok': False,
                    'provider': 'fiscal-drive-service',
                    'code': 'LOCAL_FISCAL_FAILED',
                    'detail': 'Device unavailable',
                }]),
            },
        }
        paid = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [payment_operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertTrue(paid.data['results'][0]['ok'], paid.data)
        payment = Payment.objects.get(order=order)
        payment.refresh_from_db()
        self.assertFalse(payment.register_fiscal)
        self.assertTrue(
            Receipt.objects.filter(
                payment=payment,
                kind=Receipt.Kind.PLAIN,
                status=Receipt.Status.CREATED,
            ).exists()
        )
        self.assertFalse(
            Receipt.objects.filter(payment=payment, kind=Receipt.Kind.FISCAL).exists()
        )

        retry_operation = {
            'operationId': 'edge-local-fiscal-retry-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': f'/api/v1/pos/billing/payments/{payment.id}/retry-fiscal/',
            'body': {
                'edgeFiscalResultsJson': json.dumps([{
                    'ok': True,
                    'provider': 'fiscal-drive-service',
                    'receipt_number': '72',
                    'terminal_id': 'TERM-1',
                    'response': {'TerminalID': 'TERM-1', 'ReceiptSeq': 72},
                    'request': {'receipt': {'ReceivedCash': order.total * 100, 'ReceivedCard': 0}},
                }]),
            },
        }
        retried = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [retry_operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertTrue(retried.data['results'][0]['ok'], retried.data)
        self.assertEqual(retried.data['results'][0]['status'], status.HTTP_200_OK, retried.data)
        issue_fiscal_receipts.assert_not_called()
        sent_receipt = Receipt.objects.get(payment=payment, status=Receipt.Status.SENT)
        self.assertEqual(sent_receipt.payload['receipt_number'], '72')
        self.assertEqual(sent_receipt.payload['response']['TerminalID'], 'TERM-1')

    @patch('apps.billing.services.cash_shift.close_fiscal_shift')
    @patch('apps.billing.services.cash_shift.open_fiscal_shift')
    def test_trusted_edge_fiscal_shift_results_do_not_call_remote_fiscal(
        self,
        open_fiscal_shift,
        close_fiscal_shift,
    ):
        self.assertNotIn('pos_fiscal_shift.manage', self.user.permission_codes)
        fiscal = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            kind=IntegrationConfig.Kind.FISCAL,
            provider='fiscal-drive-service',
            settings={'endpoint_url': 'http://127.0.0.1:3449'},
        )
        self.cash_desk.fiscal_integration = fiscal
        self.cash_desk.save(update_fields=['fiscal_integration', 'updated_at'])
        open_result = {
            'ok': True,
            'provider': 'fiscal-drive-service',
            'factory_id': 'FACTORY-1',
            'terminal_id': 'TERM-1',
            'response': {'TerminalID': 'TERM-1'},
        }
        open_operation = {
            'operationId': 'edge-local-fiscal-shift-open-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/fiscal-shifts/open/',
            'body': {'cashDeskId': str(self.cash_desk.id), 'edgeFiscalResultJson': json.dumps(open_result)},
        }

        opened = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [open_operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertTrue(opened.data['results'][0]['ok'], opened.data)
        open_fiscal_shift.assert_not_called()
        session = FiscalShiftSession.objects.get(restaurant=self.restaurant, status=FiscalShiftSession.Status.OPEN)
        self.assertEqual(session.terminal_id, 'TERM-1')

        close_result = {
            'ok': True,
            'provider': 'fiscal-drive-service',
            'factory_id': 'FACTORY-1',
            'terminal_id': 'TERM-1',
            'response': {'TerminalID': 'TERM-1'},
            'provider_report': {'z_info': {'TerminalID': 'TERM-1', 'TotalSaleCount': 0}},
        }
        close_operation = {
            'operationId': 'edge-local-fiscal-shift-close-1',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/fiscal-shifts/close/',
            'body': {'cashDeskId': str(self.cash_desk.id), 'edgeFiscalResultJson': json.dumps(close_result)},
        }
        closed = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [close_operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertTrue(closed.data['results'][0]['ok'], closed.data)
        close_fiscal_shift.assert_not_called()
        session.refresh_from_db()
        self.assertEqual(session.status, FiscalShiftSession.Status.CLOSED)

    @patch('apps.billing.services.cash_shift.open_fiscal_shift')
    def test_trusted_edge_fiscal_shift_command_without_local_result_still_requires_manage_permission(
        self,
        open_fiscal_shift,
    ):
        self.assertNotIn('pos_fiscal_shift.manage', self.user.permission_codes)
        operation = {
            'operationId': 'edge-remote-fiscal-shift-open-forbidden',
            'userId': str(self.user.id),
            'method': 'POST',
            'path': '/api/v1/pos/billing/fiscal-shifts/open/',
            'body': {'cashDeskId': str(self.cash_desk.id)},
        }

        response = self.client.post(
            '/api/v1/local-agent/sync/mutations/',
            {'operations': [operation]},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['results'][0]['ok'], response.data)
        self.assertEqual(response.data['results'][0]['status'], status.HTTP_403_FORBIDDEN, response.data)
        open_fiscal_shift.assert_not_called()

    @patch('apps.billing.services.cash_shift.open_fiscal_shift')
    def test_direct_pos_cannot_forge_trusted_fiscal_shift_result(self, open_fiscal_shift):
        self.assertNotIn('pos_fiscal_shift.manage', self.user.permission_codes)

        response = self.client.post(
            '/api/v1/pos/billing/fiscal-shifts/open/',
            {
                'cashDeskId': str(self.cash_desk.id),
                'edgeFiscalResult': {
                    'ok': True,
                    'provider': 'fiscal-drive-service',
                    'terminalId': 'FORGED',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        open_fiscal_shift.assert_not_called()


class LocalAgentCommandServiceTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant')
        self.agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')

    def test_execute_returns_offline_error_without_online_agent(self):
        with self.assertRaises(LocalAgentUnavailableError):
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='agent.health',
                payload={},
                timeout_seconds=1,
            )

    def test_enqueue_returns_after_command_is_dispatched_without_waiting_for_result(self):
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        result = LocalAgentCommandService().enqueue(
            restaurant=self.restaurant,
            command_type='print.document',
            payload={'operationId': 'print-operation', 'documentId': 'document-id', 'copies': 1},
            timeout_seconds=100,
        )

        self.assertTrue(result['accepted'])
        self.assertEqual(result['commandStatus'], LocalAgentCommand.Status.PENDING)
        command = LocalAgentCommand.objects.get(pk=result['commandId'])
        self.assertEqual(command.status, LocalAgentCommand.Status.PENDING)

    def test_execute_times_out_when_agent_does_not_return_result(self):
        self.agent.status = LocalAgent.Status.ONLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        with self.assertRaises(LocalAgentCommandError) as context:
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='agent.health',
                payload={},
                timeout_seconds=1,
            )

        self.assertEqual(context.exception.code, 'LOCAL_AGENT_TIMEOUT')
        self.assertIn('before it was delivered', str(context.exception))
        self.assertEqual(context.exception.result['commandStatus'], LocalAgentCommand.Status.PENDING)
        command = LocalAgentCommand.objects.get(agent=self.agent)
        self.assertEqual(command.status, LocalAgentCommand.Status.TIMED_OUT)
        self.assertEqual(command.error['commandType'], 'agent.health')
