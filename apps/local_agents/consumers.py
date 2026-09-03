import json
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import OperationalError, transaction
from django.utils import timezone

from apps.local_agents.lan import private_lan_endpoints
from apps.local_agents.device_state import pos_device_state_snapshot
from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.rollout import rollout_state_from_heartbeat
from apps.local_agents.sanitization import sanitize_remote_logs_result
from apps.local_agents.services import local_agent_group_name
from apps.devices.authentication import authenticate_device_websocket_scope
from apps.devices.migration_window import legacy_cohort_eligible, legacy_local_agent_auth_enabled
from apps.devices.models import Device


SQLITE_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def _is_database_locked(error: OperationalError) -> bool:
    return 'database is locked' in str(error).lower()


def _with_database_lock_retry(operation):
    for delay in (0, *SQLITE_LOCK_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return operation()
        except OperationalError as error:
            if not _is_database_locked(error) or delay == SQLITE_LOCK_RETRY_DELAYS[-1]:
                raise
    return None


class LocalAgentConsumer(AsyncJsonWebsocketConsumer):
    agent = None
    device = None

    async def connect(self):
        headers = {key.lower(): value for key, value in self.scope.get('headers', [])}
        authorization = headers.get(b'authorization', b'').decode('utf-8')
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer':
            token = ''
        self.agent, self.device = await self._authenticate(token)
        if self.agent is None:
            await self.close(code=4401)
            return
        self.group_name = local_agent_group_name(self.agent.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self._mark_online()
        await self.send_json(
            {
                'type': 'hello',
                'agentId': str(self.agent.id),
                'deviceId': str(self.device.id) if self.device is not None else None,
                'restaurantId': str(self.agent.restaurant_id),
                'serverTime': timezone.now().isoformat(),
                'posDevices': await self._pos_device_state(),
            }
        )
        await self._deliver_durable_terminal_revokes()

    async def disconnect(self, close_code):
        if self.agent is not None:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            # More than one valid socket can briefly exist during reconnects
            # and deployments.  Marking the shared agent row offline when any
            # one socket closes hides the still-connected socket and makes
            # commands fail spuriously.  Online state already expires through
            # LocalAgent.is_online() when heartbeats stop.

    async def receive_json(self, content, **kwargs):
        if len(json.dumps(content, separators=(',', ':')).encode('utf-8')) > 256 * 1024:
            await self.close(code=1009)
            return
        message_type = content.get('type')
        if message_type == 'heartbeat':
            if self.device is not None and not await self._device_still_active():
                await self.close(code=4403)
                return
            await self._mark_online(
                version=str(content.get('version') or ''),
                capabilities=content.get('capabilities') if isinstance(content.get('capabilities'), list) else None,
                lan_endpoints=content.get('lanEndpoints') if isinstance(content.get('lanEndpoints'), list) else None,
                protocol_version=content.get('protocolVersion'),
                rollout_state=rollout_state_from_heartbeat(content.get('legacyPosBridge')),
            )
            await self.send_json(
                {
                    'type': 'heartbeat_ack',
                    'serverTime': timezone.now().isoformat(),
                    'posDevices': await self._pos_device_state(),
                }
            )
            await self._deliver_durable_terminal_revokes()
            return
        if message_type == 'command_result':
            await self._store_command_result(content)

    async def agent_command(self, event):
        await self._mark_command_sent(event['command_id'])
        await self.send_json(
            {
                'type': 'command',
                'commandId': event['command_id'],
                'commandType': event['command_type'],
                'payload': event.get('payload') or {},
            }
        )

    async def operational_invalidate(self, event):
        await self.send_json(
            {
                'type': 'context_invalidated',
                'scopes': ['operational'],
                'serverTime': event.get('server_time') or timezone.now().isoformat(),
            }
        )

    async def device_revoked(self, event):
        await self.close(code=4403)

    async def _deliver_durable_terminal_revokes(self):
        for command in await self._durable_terminal_revokes():
            await self.agent_command(command)

    @database_sync_to_async
    def _durable_terminal_revokes(self):
        commands = (
            LocalAgentCommand.objects.filter(
                agent=self.agent,
                command_type='edge.terminal.revoke',
            )
            .exclude(status=LocalAgentCommand.Status.SUCCEEDED)
            .order_by('created_at')[:100]
        )
        return [
            {
                'command_id': str(command.id),
                'command_type': command.command_type,
                'payload': command.payload or {},
            }
            for command in commands
        ]

    @database_sync_to_async
    def _pos_device_state(self):
        return pos_device_state_snapshot(restaurant=self.agent.restaurant)

    @database_sync_to_async
    def _authenticate(self, token):
        device = authenticate_device_websocket_scope(self.scope, expected_types=[Device.Type.LOCAL_AGENT])
        if device is not None:
            agent = LocalAgent.objects.select_related('restaurant').filter(
                device=device,
                restaurant=device.restaurant,
                is_active=True,
            ).first()
            return agent, device
        if not legacy_local_agent_auth_enabled():
            return None, None
        # See HTTP authentication: a legacy process may still need the
        # bounded bridge long enough to update and re-key itself.
        agent = LocalAgent.authenticate_token(token, allow_migrated=True)
        if agent is None or not legacy_cohort_eligible(created_at=agent.created_at):
            return None, None
        return agent, None

    @database_sync_to_async
    def _device_still_active(self):
        return Device.objects.filter(
            pk=self.device.pk,
            status=Device.Status.ACTIVE,
            revoked_at__isnull=True,
            lease_expires_at__gt=timezone.now(),
        ).exists()

    @database_sync_to_async
    def _mark_online(
        self,
        *,
        version='',
        capabilities=None,
        lan_endpoints=None,
        protocol_version=None,
        rollout_state=None,
    ):
        now = timezone.now()
        values = {
            'status': LocalAgent.Status.ONLINE,
            'last_seen_at': now,
            'updated_at': now,
        }
        if version:
            values['version'] = version
        if capabilities is not None:
            values['capabilities'] = capabilities
        if lan_endpoints is not None:
            values['lan_endpoints'] = private_lan_endpoints(lan_endpoints)
        if isinstance(protocol_version, int) and 1 <= protocol_version <= 255:
            values['protocol_version'] = protocol_version
        if rollout_state is not None:
            values['rollout_state'] = rollout_state

        def persist_heartbeat():
            with transaction.atomic():
                LocalAgent.objects.filter(pk=self.agent.pk).update(**values)
                if self.device is not None:
                    device_values = {
                        'last_seen_at': now,
                        'updated_at': now,
                    }
                    if version:
                        device_values['app_version'] = version
                    Device.objects.filter(pk=self.device.pk).update(**device_values)

        _with_database_lock_retry(persist_heartbeat)

    @database_sync_to_async
    def _mark_command_sent(self, command_id):
        _with_database_lock_retry(
            lambda: LocalAgentCommand.objects.filter(pk=command_id, agent=self.agent).update(
                status=LocalAgentCommand.Status.SENT,
                sent_at=timezone.now(),
                updated_at=timezone.now(),
            )
        )

    @database_sync_to_async
    def _store_command_result(self, content):
        command_id = content.get('commandId') or content.get('command_id')
        ok = content.get('ok') is True
        result = content.get('result') if isinstance(content.get('result'), dict) else {}
        error = content.get('error') if isinstance(content.get('error'), dict) else {}
        command = LocalAgentCommand.objects.filter(pk=command_id, agent=self.agent).only('command_type').first()
        if command is not None and command.command_type == 'agent.logs':
            result = sanitize_remote_logs_result(result)
        _with_database_lock_retry(
            lambda: LocalAgentCommand.objects.filter(pk=command_id, agent=self.agent).update(
                status=LocalAgentCommand.Status.SUCCEEDED if ok else LocalAgentCommand.Status.FAILED,
                result=result,
                error=error,
                completed_at=timezone.now(),
                updated_at=timezone.now(),
            )
        )
