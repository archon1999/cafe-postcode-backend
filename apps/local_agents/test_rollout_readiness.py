import json
from datetime import timedelta, timezone as datetime_timezone

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.devices.models import Device
from apps.local_agents.models import LocalAgent
from apps.local_agents.rollout import (
    SERVER_BRIDGE_FAILURE_INVALID,
    SERVER_BRIDGE_FAILURE_MISSING,
    rollout_state_from_heartbeat,
    sanitize_legacy_pos_bridge_heartbeat,
)
from apps.restaurants.models import Restaurant
from apps.users.models import User


def _utc_seconds(value):
    return value.astimezone(datetime_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _bridge_payload(now, **updates):
    payload = {
        'configured': True,
        'enabled': True,
        'failure': '',
        'sourceCommit': 'a' * 40,
        'builtAt': _utc_seconds(now - timedelta(minutes=5)),
        'notAfter': _utc_seconds(now + timedelta(hours=1)),
        'lastSeenAt': _utc_seconds(now - timedelta(seconds=5)),
        'terminalCount': 1,
    }
    payload.update(updates)
    return payload


class LegacyPOSBridgeHeartbeatValidationTests(SimpleTestCase):
    def test_valid_payload_is_canonical_and_secret_free(self):
        now = timezone.now().replace(microsecond=0)
        payload = _bridge_payload(now)

        sanitized = sanitize_legacy_pos_bridge_heartbeat(payload, received_at=now)

        self.assertEqual(sanitized, payload)

    def test_thirty_day_payload_is_valid(self):
        now = timezone.now().replace(microsecond=0)
        payload = _bridge_payload(
            now,
            builtAt=_utc_seconds(now - timedelta(minutes=1)),
            notAfter=_utc_seconds(now + timedelta(days=30) - timedelta(minutes=1)),
        )

        sanitized = sanitize_legacy_pos_bridge_heartbeat(payload, received_at=now)

        self.assertEqual(sanitized, payload)

    def test_unknown_or_cross_field_invalid_payload_fails_closed(self):
        now = timezone.now().replace(microsecond=0)
        cases = (
            {**_bridge_payload(now), 'edgeToken': 'ept_secret'},
            _bridge_payload(now, configured=False),
            _bridge_payload(now, sourceCommit='A' * 40),
            _bridge_payload(now, terminalCount=True),
            _bridge_payload(
                now,
                notAfter=_utc_seconds(now + timedelta(days=32)),
            ),
            _bridge_payload(
                now,
                notAfter=_utc_seconds(now - timedelta(seconds=1)),
            ),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(
                    sanitize_legacy_pos_bridge_heartbeat(payload, received_at=now),
                    {
                        'configured': False,
                        'enabled': False,
                        'failure': SERVER_BRIDGE_FAILURE_INVALID,
                    },
                )

    def test_missing_bridge_and_final_artifact_are_distinguishable(self):
        now = timezone.now().replace(microsecond=0)
        self.assertEqual(
            sanitize_legacy_pos_bridge_heartbeat(None, received_at=now)['failure'],
            SERVER_BRIDGE_FAILURE_MISSING,
        )
        self.assertEqual(
            sanitize_legacy_pos_bridge_heartbeat(
                {
                    'configured': False,
                    'enabled': False,
                    'failure': 'bridge_not_configured',
                    'lastSeenAt': _utc_seconds(now - timedelta(minutes=1)),
                    'terminalCount': 2,
                },
                received_at=now,
            ),
            {
                'configured': False,
                'enabled': False,
                'failure': 'bridge_not_configured',
                'lastSeenAt': _utc_seconds(now - timedelta(minutes=1)),
                'terminalCount': 2,
            },
        )


@override_settings(DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED=True)
class LocalAgentRolloutHeartbeatTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Bridge Coverage Restaurant')
        self.foreign_restaurant = Restaurant.objects.create(name='Spoofed Restaurant')
        _agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)

    def test_heartbeat_is_server_scoped_and_invalid_update_clears_stale_readiness(self):
        from core.asgi import application

        now = timezone.now().replace(microsecond=0)

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
                    'version': '0.9.1-bridge',
                    'protocolVersion': 3,
                    'capabilities': ['local_http', 'legacy_pos_bridge_bounded'],
                    'restaurantId': str(self.foreign_restaurant.id),
                    'legacyPosBridge': _bridge_payload(now),
                }
            )
            acknowledgement = await communicator.receive_json_from()
            self.assertEqual(acknowledgement['type'], 'heartbeat_ack')
            await communicator.disconnect()

        async_to_sync(run_scenario)()
        agent = LocalAgent.objects.get(restaurant=self.restaurant)
        self.assertEqual(agent.version, '0.9.1-bridge')
        self.assertEqual(agent.protocol_version, 3)
        self.assertEqual(agent.rollout_state['legacyPosBridge'], _bridge_payload(now))
        self.assertNotIn(str(self.foreign_restaurant.id), json.dumps(agent.rollout_state))

        async def send_invalid_update():
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
                    'version': '0.9.1-bridge',
                    'legacyPosBridge': {**_bridge_payload(now), 'token': 'ept_must_not_persist'},
                }
            )
            await communicator.receive_json_from()
            await communicator.disconnect()

        async_to_sync(send_invalid_update)()
        agent.refresh_from_db()
        self.assertEqual(agent.rollout_state['legacyPosBridge']['failure'], SERVER_BRIDGE_FAILURE_INVALID)
        self.assertNotIn('ept_must_not_persist', json.dumps(agent.rollout_state))


class DeviceMigrationBranchSummaryTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='rollout-summary-admin',
            password='Strong-Rollout-Summary-123!',
        )
        self.client.force_authenticate(self.admin)

    def test_summary_exposes_per_branch_non_authoritative_bridge_coverage(self):
        now = timezone.now().replace(microsecond=0)
        covered = Restaurant.objects.create(name='Covered Branch')
        uncovered = Restaurant.objects.create(name='Uncovered Branch')
        agent, _token = LocalAgent.issue_for_restaurant(
            restaurant=covered,
            name='Covered Agent',
            version='0.9.1-bridge',
        )
        agent.status = LocalAgent.Status.ONLINE
        agent.last_seen_at = now
        agent.protocol_version = 3
        agent.capabilities = ['local_http', 'legacy_pos_bridge_bounded']
        agent.rollout_state = rollout_state_from_heartbeat(_bridge_payload(now), received_at=now)
        agent.save(
            update_fields=[
                'status',
                'last_seen_at',
                'protocol_version',
                'capabilities',
                'rollout_state',
                'updated_at',
            ]
        )
        Device.objects.create(
            restaurant=covered,
            type=Device.Type.POS_TERMINAL,
            name='Covered POS',
            public_key_algorithm=Device.PublicKeyAlgorithm.P256_SHA256,
            public_key='test-public-key',
            public_key_fingerprint='f' * 64,
            paired_at=now,
            lease_expires_at=now + timedelta(days=30),
            last_seen_at=now,
        )

        response = self.client.get('/api/v1/admin/devices/migration-summary/')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        branches = {item['restaurantName']: item for item in response.data['branches']}
        self.assertEqual(branches['Covered Branch']['activePOSDevices'], 1)
        self.assertEqual(branches['Covered Branch']['agent']['version'], '0.9.1-bridge')
        self.assertEqual(branches['Covered Branch']['agent']['lastSeenAt'], now.isoformat())
        self.assertTrue(branches['Covered Branch']['agent']['bridge']['checkInObserved'])
        self.assertTrue(branches['Covered Branch']['agent']['bridge']['readyForPOSUpdate'])
        self.assertIsNone(branches['Uncovered Branch']['agent'])

        regular_user = User.objects.create_user(username='rollout-summary-user', password='unused')
        self.client.force_authenticate(regular_user)
        denied = self.client.get('/api/v1/admin/devices/migration-summary/')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
