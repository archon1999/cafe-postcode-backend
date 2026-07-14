import uuid
from unittest.mock import patch

from django.utils import timezone
from django.test import TransactionTestCase, override_settings
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from rest_framework import status
from rest_framework.test import APITestCase

from apps.local_agents.models import (
    LocalAgent,
    LocalAgentCommand,
    LocalAgentEnrollmentToken,
    LocalAgentMutationReceipt,
)
from apps.local_agents.mutations import _allowed_mutation, _request_hash
from apps.billing.models import CashShift, Payment
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError
from apps.integrations.models import IntegrationConfig
from apps.printing.models import PrintDocument, PrintTemplate
from apps.printing.services import ensure_restaurant_templates
from apps.restaurants.models import CashDesk, PrepStation, Restaurant
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import User


class LocalAgentAuthTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant', auth_code='123456')

    def issue_enrollment_token(self):
        _enrollment, raw_token = LocalAgentEnrollmentToken.issue(restaurant=self.restaurant)
        return raw_token

    def test_enrollment_returns_agent_token(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/enroll/',
            {'restaurantCode': self.restaurant.auth_code, 'name': 'Cashier PC', 'version': '0.2.0'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['agentToken'].startswith('cpa_'))
        self.assertIn('/ws/local-agent/', response.data['wsUrl'])
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.name, 'Cashier PC')
        self.assertTrue(LocalAgent.authenticate_token(response.data['agentToken']))

    def test_token_auth_returns_agent_metadata(self):
        _agent, token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')

        response = self.client.get('/api/v1/local-agent/auth/token/', HTTP_AUTHORIZATION=f'Bearer {token}')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['agent']['restaurant_name'], 'Agent Restaurant')

    def test_token_auth_rejects_invalid_token(self):
        response = self.client.get('/api/v1/local-agent/auth/token/', HTTP_AUTHORIZATION='Bearer cpa_bad')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_restaurant_code_can_reinstall_agent(self):
        payload = {'restaurantCode': self.restaurant.auth_code, 'name': 'Cashier PC'}

        first = self.client.post('/api/v1/local-agent/auth/enroll/', payload, format='json')
        second = self.client.post('/api/v1/local-agent/auth/enroll/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertNotEqual(first.data['agentToken'], second.data['agentToken'])

    def test_restaurant_code_preflight_allows_enrollment(self):
        preflight = self.client.post(
            '/api/v1/local-agent/auth/enrollment/preflight/',
            {'restaurantCode': self.restaurant.auth_code, 'name': 'Cashier PC'},
            format='json',
        )
        enroll = self.client.post(
            '/api/v1/local-agent/auth/enroll/',
            {'restaurantCode': self.restaurant.auth_code, 'name': 'Cashier PC'},
            format='json',
        )

        self.assertEqual(preflight.status_code, status.HTTP_200_OK, preflight.data)
        self.assertEqual(preflight.data['restaurantId'], str(self.restaurant.id))
        self.assertEqual(enroll.status_code, status.HTTP_200_OK, enroll.data)

    def test_enrollment_preflight_rejects_invalid_restaurant_code(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/enrollment/preflight/',
            {'restaurantCode': 'BAD000'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_enrollment_rejects_invalid_restaurant_code(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/enroll/',
            {'restaurantCode': 'BAD000'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_restaurant_code_enrollment_endpoint_is_removed(self):
        response = self.client.post(
            '/api/v1/local-agent/auth/restaurant-code/',
            {'code': self.restaurant.auth_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_can_issue_hashed_enrollment_token(self):
        other_restaurant = Restaurant.objects.create(name='Other Restaurant', auth_code='OT1234')
        admin = User.objects.create_superuser(
            username='agent-enrollment-admin',
            password='Strong-Agent-Admin-123!',
            full_name='Agent Enrollment Admin',
        )
        self.client.force_authenticate(admin)

        response = self.client.post(
            '/api/v1/local-agent/enrollment-token/',
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(self.restaurant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data['enrollmentToken'].startswith('cpe_'))
        enrollment = LocalAgentEnrollmentToken.objects.get(restaurant=self.restaurant)
        self.assertNotEqual(enrollment.token_hash, response.data['enrollmentToken'])
        self.assertFalse(LocalAgentEnrollmentToken.objects.filter(restaurant=other_restaurant).exists())

    def test_admin_cannot_issue_enrollment_token_for_inactive_restaurant(self):
        inactive_restaurant = Restaurant.objects.create(
            name='Inactive Restaurant',
            auth_code='IN1234',
            is_active=False,
        )
        admin = User.objects.create_superuser(
            username='inactive-agent-enrollment-admin',
            password='Strong-Agent-Admin-123!',
            full_name='Inactive Agent Enrollment Admin',
        )
        self.client.force_authenticate(admin)

        response = self.client.post(
            '/api/v1/local-agent/enrollment-token/',
            format='json',
            HTTP_X_ADMIN_RESTAURANT_ID=str(inactive_restaurant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(LocalAgentEnrollmentToken.objects.filter(restaurant=inactive_restaurant).exists())


class LocalAgentWebSocketSecurityTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='WebSocket Restaurant', auth_code='WS1234')
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
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.version, '0.6.0')
        self.assertEqual(agent.protocol_version, 2)
        self.assertEqual(agent.lan_endpoints, ['http://192.168.1.20:18181'])

    @override_settings(LOCAL_AGENT_ALLOW_LEGACY_WS_QUERY_TOKEN=True)
    def test_legacy_query_token_can_be_enabled_only_for_rollout(self):
        from core.asgi import application

        async def run_scenario():
            communicator = WebsocketCommunicator(
                application,
                f'/ws/local-agent/?token={self.token}',
                headers=[(b'origin', b'http://testserver')],
            )
            connected, _subprotocol = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.disconnect()

        async_to_sync(run_scenario)()


class LocalAgentPrintDocumentTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant', auth_code='123456')
        self.foreign_restaurant = Restaurant.objects.create(name='Foreign Restaurant', auth_code='654321')
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
        self.assertNotIn('settings', response.data['route']['printer'])

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

    @patch('apps.printing.api.pos.views.LocalAgentCommandService.execute')
    def test_remote_pos_print_routes_document_to_restaurants_agent(self, execute):
        execute.return_value = {
            'job': {
                'operationId': 'pos:remote-print-123',
                'documentId': str(self.document.id),
                'copies': 1,
                'status': 'succeeded',
            }
        }

        response = self.client.post(
            '/api/v1/pos/printing/jobs/',
            {
                'operation_id': 'pos:remote-print-123',
                'document_id': str(self.document.id),
                'copies': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['job']['status'], 'succeeded')
        execute.assert_called_once_with(
            restaurant=self.restaurant,
            command_type='print.document',
            payload={
                'operationId': 'pos:remote-print-123',
                'documentId': str(self.document.id),
                'copies': 1,
            },
            timeout_seconds=100,
        )


class LocalAgentBootstrapTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        self.user.set_pin('1234')
        self.user.save(update_fields=['pin_code'])
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')

    def test_bootstrap_returns_offline_context_scoped_to_agent_restaurant(self):
        shift = CashShift.objects.create(
            cash_desk=self.cash_desk,
            cashier=self.user,
            opened_by=self.user,
            status=CashShift.Status.OPEN,
            opened_at=timezone.now(),
            opening_cash_amount=125000,
        )
        response = self.client.get(
            '/api/v1/local-agent/sync/bootstrap/',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['schemaVersion'], 1)
        self.assertEqual(response.data['restaurant']['restaurant_id'], str(self.restaurant.id))
        self.assertEqual(response.data['users'][0]['userId'], str(self.user.id))
        self.assertTrue(response.data['users'][0]['pinHash'].startswith('pbkdf2_'))
        self.assertGreaterEqual(len(response.data['menu']), 1)
        self.assertGreaterEqual(len(response.data['halls']), 1)
        self.assertEqual(response.data['bindings']['cashDesks'][0]['id'], str(self.cash_desk.id))
        self.assertEqual(response.data['cashShifts'][0]['id'], str(shift.id))
        self.assertEqual(response.data['cashShifts'][0]['cashier'], str(self.user.id))
        self.assertEqual(response.data['cashShifts'][0]['openingCashAmount'], 125000)

    def test_bootstrap_requires_agent_token(self):
        response = self.client.get('/api/v1/local-agent/sync/bootstrap/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LocalAgentMutationPushTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Site coordinator')

    def test_order_create_mutation_is_replayed_once(self):
        order_id = uuid.uuid4()
        operation = {
            'operationId': 'edge-order-create-1',
            'userId': str(self.user.id),
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
        operations = [
            {
                'operationId': 'edge-shift-open-1',
                'userId': str(self.user.id),
                'method': 'POST',
                'path': '/api/v1/pos/billing/shifts/open/',
                'body': {'cashDeskId': str(self.cash_desk.id), 'openingCashAmount': 10000},
            },
            {
                'operationId': 'edge-shift-close-1',
                'userId': str(self.user.id),
                'method': 'POST',
                'path': '/api/v1/pos/billing/shifts/current/close/',
                'body': {
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
        self.assertEqual(shift.status, CashShift.Status.CLOSED)

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


class LocalAgentCommandServiceTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Agent Restaurant', auth_code='123456')
        self.agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Cashier PC')

    def test_execute_returns_offline_error_without_online_agent(self):
        with self.assertRaises(LocalAgentUnavailableError):
            LocalAgentCommandService().execute(
                restaurant=self.restaurant,
                command_type='agent.health',
                payload={},
                timeout_seconds=1,
            )

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
