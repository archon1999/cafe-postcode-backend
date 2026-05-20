import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import OperationalError
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


class LocalAgentConsumer(AsyncJsonWebsocketConsumer):
    agent = None

    async def connect(self):
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
        message_type = content.get('type')
        if message_type == 'heartbeat':
            await self._mark_online(
                version=str(content.get('version') or ''),
                capabilities=content.get('capabilities') if isinstance(content.get('capabilities'), list) else None,
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
    def _mark_online(self, *, version='', capabilities=None):
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
