import base64
import hashlib
import os
import time
import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.utils import timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from apps.devices.crypto import device_request_message, sha256_hex
from apps.devices.models import Device
from apps.local_agents.connection_authority import (
    ConnectionIdentity,
    claim_connection_authority,
    connection_identity_from_scope,
    release_connection_authority,
)
from apps.local_agents.models import LocalAgent, LocalAgentCommand, LocalAgentConnection
from apps.local_agents.services import local_agent_group_name
from apps.restaurants.models import Restaurant


class LocalAgentConnectionIdentityTests(TransactionTestCase):
    def test_signed_runtime_query_is_strict_and_legacy_query_remains_empty(self):
        query = b'agentVersion=1.1.14&instanceId=abcdefghijklmnopqrstuv&protocolVersion=3'
        identity = connection_identity_from_scope(
            {'query_string': query},
            device_authenticated=True,
        )
        self.assertEqual(identity.version, '1.1.14')
        self.assertEqual(identity.runtime_instance_id, 'abcdefghijklmnopqrstuv')
        self.assertEqual(identity.protocol_version, 3)
        self.assertTrue(identity.attested)
        self.assertEqual(
            connection_identity_from_scope({'query_string': b''}, device_authenticated=False),
            ConnectionIdentity(),
        )

        for invalid in (
            query + b'&agentVersion=9.9.9',
            b'agentVersion=1.1.14&instanceId=short&protocolVersion=3',
            b'agentVersion=1.1.14&instanceId=abcdefghijklmnopqrstuv',
            query + b'&token=secret',
        ):
            with self.subTest(query=invalid):
                self.assertIsNone(
                    connection_identity_from_scope(
                        {'query_string': invalid},
                        device_authenticated=True,
                    )
                )

        self.assertIsNone(
            connection_identity_from_scope(
                {'query_string': query},
                device_authenticated=False,
            )
        )


class LocalAgentConnectionLeaseTests(TransactionTestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Authority Restaurant')
        self.agent, _token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)
        self.now = timezone.now()

    def claim(self, *, identity, channel, now=None):
        return claim_connection_authority(
            agent_id=self.agent.id,
            connection_id=uuid.uuid4(),
            channel_name=channel,
            identity=identity,
            now=now or self.now,
        )

    def test_only_one_same_version_socket_is_authoritative(self):
        first = self.claim(identity=ConnectionIdentity(), channel='first')
        second = self.claim(identity=ConnectionIdentity(), channel='second')
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        lease = LocalAgentConnection.objects.get(agent=self.agent)
        self.assertEqual(lease.channel_name, 'first')

    def test_higher_attested_version_supersedes_legacy_socket(self):
        self.assertTrue(self.claim(identity=ConnectionIdentity(), channel='legacy').accepted)
        newer = self.claim(
            identity=ConnectionIdentity(
                version='1.1.14',
                runtime_instance_id='abcdefghijklmnopqrstuv',
                protocol_version=3,
                attested=True,
            ),
            channel='newer',
        )
        self.assertTrue(newer.accepted)
        self.assertEqual(newer.displaced_channel_name, 'legacy')
        lease = LocalAgentConnection.objects.get(agent=self.agent)
        self.assertEqual(lease.version, '1.1.14')
        self.assertEqual(lease.channel_name, 'newer')

    def test_lower_version_waits_during_holdoff_but_recovers_after_expiry(self):
        current_id = uuid.uuid4()
        current = ConnectionIdentity(
            version='1.1.14',
            runtime_instance_id='abcdefghijklmnopqrstuv',
            protocol_version=3,
            attested=True,
        )
        claim = claim_connection_authority(
            agent_id=self.agent.id,
            connection_id=current_id,
            channel_name='newer',
            identity=current,
            now=self.now,
        )
        self.assertTrue(claim.accepted)
        self.assertTrue(
            release_connection_authority(
                agent_id=self.agent.id,
                connection_id=current_id,
                now=self.now + timedelta(seconds=1),
            )
        )
        lower = ConnectionIdentity(
            version='1.1.13',
            runtime_instance_id='zyxwvutsrqponmlkjihgfe',
            protocol_version=3,
            attested=True,
        )
        blocked = self.claim(
            identity=lower,
            channel='rollback-early',
            now=self.now + timedelta(seconds=30),
        )
        self.assertFalse(blocked.accepted)
        recovered = self.claim(
            identity=lower,
            channel='rollback-late',
            now=self.now + timedelta(seconds=92),
        )
        self.assertTrue(recovered.accepted)

    def test_same_runtime_instance_can_replace_its_stale_transport(self):
        identity = ConnectionIdentity(
            version='1.1.14',
            runtime_instance_id='abcdefghijklmnopqrstuv',
            protocol_version=3,
            attested=True,
        )
        first = self.claim(identity=identity, channel='socket-1')
        second = self.claim(identity=identity, channel='socket-2')
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(second.displaced_channel_name, 'socket-1')


class LocalAgentAuthoritativeWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Socket Authority Restaurant')
        self.agent, self.token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant)

    def test_duplicate_socket_cannot_receive_or_complete_commands(self):
        from core.asgi import application

        async def run_scenario():
            first = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode()),
                ],
            )
            connected, _ = await first.connect()
            self.assertTrue(connected)
            self.assertEqual((await first.receive_json_from())['type'], 'hello')

            duplicate = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode()),
                ],
            )
            duplicate_connected, _ = await duplicate.connect()
            self.assertTrue(duplicate_connected)
            duplicate_close = await duplicate.receive_output()
            self.assertEqual(duplicate_close['type'], 'websocket.close')
            self.assertEqual(duplicate_close['code'], 4410)

            command = await LocalAgentCommand.objects.acreate(
                agent=self.agent,
                command_type='system.status',
                payload={},
            )
            await get_channel_layer().group_send(
                local_agent_group_name(self.agent.id),
                {
                    'type': 'agent.command',
                    'command_id': str(command.id),
                    'command_type': command.command_type,
                    'payload': command.payload,
                },
            )
            delivered = await first.receive_json_from()
            self.assertEqual(delivered['type'], 'command')
            self.assertEqual(delivered['commandId'], str(command.id))
            await first.send_json_to(
                {
                    'type': 'command_result',
                    'commandId': str(command.id),
                    'ok': True,
                    'result': {'source': 'authority'},
                }
            )
            await first.disconnect()

        async_to_sync(run_scenario)()
        command = LocalAgentCommand.objects.get(command_type='system.status')
        self.assertEqual(command.status, LocalAgentCommand.Status.SUCCEEDED)
        self.assertEqual(command.result, {'source': 'authority'})
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.status, LocalAgent.Status.OFFLINE)

    def test_signed_newer_agent_supersedes_legacy_socket_and_owns_version(self):
        from core.asgi import application

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        b64url = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
        now = timezone.now()
        device = Device.objects.create(
            restaurant=self.restaurant,
            type=Device.Type.LOCAL_AGENT,
            name='Signed Agent',
            platform='windows-amd64',
            app_version='1.1.13',
            public_key_algorithm=Device.PublicKeyAlgorithm.ED25519,
            public_key=b64url(public_key),
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            paired_at=now,
            lease_expires_at=now + timedelta(days=1),
        )
        self.agent.device = device
        self.agent.save(update_fields=['device', 'updated_at'])
        query = 'agentVersion=1.1.14&instanceId=abcdefghijklmnopqrstuv&protocolVersion=3'
        path = f'/ws/local-agent/?{query}'
        timestamp = int(time.time())
        nonce = b64url(os.urandom(24))
        body_hash = sha256_hex(b'')
        message = device_request_message(
            method='GET',
            request_target=path,
            device_id=device.pk,
            timestamp=timestamp,
            nonce=nonce,
            body_sha256=body_hash,
        )
        signature = b64url(private_key.sign(message.encode('utf-8')))
        signed_headers = [
            (b'origin', b'http://testserver'),
            (b'x-device-id', str(device.pk).encode()),
            (b'x-device-timestamp', str(timestamp).encode()),
            (b'x-device-nonce', nonce.encode()),
            (b'x-device-content-sha256', body_hash.encode()),
            (b'x-device-signature', signature.encode()),
        ]

        async def run_scenario():
            legacy = WebsocketCommunicator(
                application,
                '/ws/local-agent/',
                headers=[
                    (b'origin', b'http://testserver'),
                    (b'authorization', f'Bearer {self.token}'.encode()),
                ],
            )
            connected, _ = await legacy.connect()
            self.assertTrue(connected)
            self.assertEqual((await legacy.receive_json_from())['type'], 'hello')

            signed = WebsocketCommunicator(application, path, headers=signed_headers)
            signed_connected, _ = await signed.connect()
            self.assertTrue(signed_connected)
            hello = await signed.receive_json_from()
            self.assertEqual(hello['type'], 'hello')
            self.assertEqual(hello['deviceId'], str(device.id))
            await signed.send_json_to(
                {
                    'type': 'heartbeat',
                    'version': '1.1.14',
                    'protocolVersion': 3,
                    'capabilities': ['system_health'],
                    'lanEndpoints': ['http://192.168.1.20:18181'],
                }
            )
            self.assertEqual((await signed.receive_json_from())['type'], 'heartbeat_ack')
            displaced = await legacy.receive_output()
            self.assertEqual(displaced['type'], 'websocket.close')
            self.assertEqual(displaced['code'], 4410)

            command = await LocalAgentCommand.objects.acreate(
                agent=self.agent,
                command_type='system.status',
                payload={},
            )
            await get_channel_layer().group_send(
                local_agent_group_name(self.agent.id),
                {
                    'type': 'agent.command',
                    'command_id': str(command.id),
                    'command_type': command.command_type,
                    'payload': command.payload,
                },
            )
            delivered = await signed.receive_json_from()
            self.assertEqual(delivered['commandId'], str(command.id))
            # The signed query is the immutable runtime claim. A stale process
            # cannot reuse this socket to overwrite the fleet version later.
            await signed.send_json_to(
                {
                    'type': 'heartbeat',
                    'version': '1.1.13',
                    'protocolVersion': 3,
                }
            )
            mismatch_close = await signed.receive_output()
            self.assertEqual(mismatch_close['type'], 'websocket.close')
            self.assertEqual(mismatch_close['code'], 4410)

        async_to_sync(run_scenario)()
        self.agent.refresh_from_db()
        device.refresh_from_db()
        self.assertEqual(self.agent.version, '1.1.14')
        self.assertEqual(device.app_version, '1.1.14')
