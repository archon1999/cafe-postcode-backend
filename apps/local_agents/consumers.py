import ipaddress
import json
import time
from urllib.parse import parse_qs, urlsplit

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import OperationalError
from django.conf import settings
from django.utils import timezone

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.local_agents.services import local_agent_group_name


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


def _private_lan_endpoints(values):
    endpoints = []
    for value in values[:8]:
        if not isinstance(value, str) or len(value) > 255:
            continue
        try:
            parsed = urlsplit(value)
            address = ipaddress.ip_address(parsed.hostname or '')
            port = parsed.port
        except (ValueError, TypeError):
            continue
        if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path not in ('', '/'):
            continue
        if address.version != 4 or not address.is_private or address.is_loopback or not port:
            continue
        endpoints.append(f'http://{address}:{port}')
    return endpoints


class LocalAgentConsumer(AsyncJsonWebsocketConsumer):
    agent = None

    async def connect(self):
        headers = {key.lower(): value for key, value in self.scope.get('headers', [])}
        authorization = headers.get(b'authorization', b'').decode('utf-8')
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer':
            token = ''
        if not token and settings.LOCAL_AGENT_ALLOW_LEGACY_WS_QUERY_TOKEN:
            query = parse_qs(self.scope.get('query_string', b'').decode('utf-8'))
            token = (query.get('token') or [''])[0]
        self.agent = await self._authenticate(token)
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
                'restaurantId': str(self.agent.restaurant_id),
                'serverTime': timezone.now().isoformat(),
            }
        )

    async def disconnect(self, close_code):
        if self.agent is not None:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self._mark_offline()

    async def receive_json(self, content, **kwargs):
        if len(json.dumps(content, separators=(',', ':')).encode('utf-8')) > 256 * 1024:
            await self.close(code=1009)
            return
        message_type = content.get('type')
        if message_type == 'heartbeat':
            await self._mark_online(
                version=str(content.get('version') or ''),
                capabilities=content.get('capabilities') if isinstance(content.get('capabilities'), list) else None,
                lan_endpoints=content.get('lanEndpoints') if isinstance(content.get('lanEndpoints'), list) else None,
                protocol_version=content.get('protocolVersion'),
            )
            await self.send_json({'type': 'heartbeat_ack', 'serverTime': timezone.now().isoformat()})
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

    @database_sync_to_async
    def _authenticate(self, token):
        return LocalAgent.authenticate_token(token)

    @database_sync_to_async
    def _mark_online(self, *, version='', capabilities=None, lan_endpoints=None, protocol_version=None):
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
            values['lan_endpoints'] = _private_lan_endpoints(lan_endpoints)
        if isinstance(protocol_version, int) and 1 <= protocol_version <= 255:
            values['protocol_version'] = protocol_version
        _with_database_lock_retry(lambda: LocalAgent.objects.filter(pk=self.agent.pk).update(**values))

    @database_sync_to_async
    def _mark_offline(self):
        _with_database_lock_retry(
            lambda: LocalAgent.objects.filter(pk=self.agent.pk).update(
                status=LocalAgent.Status.OFFLINE,
                updated_at=timezone.now(),
            )
        )

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
        _with_database_lock_retry(
            lambda: LocalAgentCommand.objects.filter(pk=command_id, agent=self.agent).update(
                status=LocalAgentCommand.Status.SUCCEEDED if ok else LocalAgentCommand.Status.FAILED,
                result=result,
                error=error,
                completed_at=timezone.now(),
                updated_at=timezone.now(),
            )
        )
